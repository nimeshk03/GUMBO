"""
Gumbo Engine - Core Intelligent Suggestion System

Production-grade implementation of the Gumbo algorithm for automated,
context-aware suggestion generation based on user behavior patterns.

Algorithm Flow:
1. Automatic Trigger: New proposition with confidence ≥ 8
2. Contextual Retrieval: LLM-based semantic similarity search
3. Multi-Candidate Generation: Generate 5 suggestions using context
4. Mixed-Initiative Filtering: Score suggestions using Expected Utility
5. Rate Limiting: Token bucket prevents spam
6. Real-Time Push: SSE delivery to frontend
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from sqlalchemy.orm import selectinload

# Import existing GUM components
from ..db_utils import search_propositions_bm25
from ..models import Proposition, Observation
from ..suggestion_models import (
    SuggestionData, SuggestionBatch, UtilityScores, 
    ContextualProposition, ContextRetrievalResult,
    SSEEvent, SSEEventType
)
from .rate_limiter import get_rate_limiter

# Import unified AI client
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from unified_ai_client import get_unified_client

logger = logging.getLogger(__name__)


# Production-grade prompts for Gumbo algorithm
CONTEXTUAL_RETRIEVAL_PROMPT = """You are a behavioral pattern analyst. Analyze the trigger proposition and generate a semantic search query to find related behavioral insights.

TRIGGER PROPOSITION:
"{trigger_text}"

REASONING: {trigger_reasoning}

Generate a focused search query (2-4 keywords) that will find related behavioral patterns, workflows, or user preferences that could inform actionable suggestions.

Return only the search query, no explanation."""

MULTI_CANDIDATE_GENERATION_PROMPT = """You are an intelligent behavioral assistant that provides highly contextual, personalized suggestions with direct solutions when possible.

CURRENT BEHAVIORAL TRIGGER:
The user just demonstrated: "{trigger_text}"

RELATED BEHAVIORAL PATTERNS:
{related_context}

ADVANCED ANALYSIS FRAMEWORK:
Analyze the behavioral data to identify:

1. **Specific Challenges**: What concrete problems, knowledge gaps, or obstacles does the user face?
2. **Timing Patterns**: When does the user work? Are there productivity/focus timing insights?
3. **Content Context**: What specific content, tools, or domains is the user working with?
4. **Workflow Inefficiencies**: What repetitive tasks, suboptimal processes, or friction points exist?
5. **Cross-Pattern Insights**: How do multiple behavioral patterns interact to reveal opportunities?

SOLUTION-FIRST APPROACH:
When identifying gaps or research needs, PROVIDE the actual solution when possible:
- If user needs missing terminology → Include the actual terms/definitions
- If user needs research links → Provide relevant URLs or resources  
- If user needs explanations → Give brief, actionable explanations
- If user needs examples → Include specific examples
- If user needs steps → List the actual steps
- If user needs answers → Provide the answers directly

Only suggest "research X" when the information is too complex, personal, or specialized to provide directly.

TASK: Generate 5 sophisticated, solution-oriented suggestions that:
- SOLVE specific challenges mentioned in the behavioral data (don't just suggest research)
- PROVIDE actual information, links, terminology, or answers when possible
- LEVERAGE timing insights for better scheduling/focus
- INCLUDE concrete solutions with specific details
- CROSS-REFERENCE multiple behavioral patterns for comprehensive solutions

SUGGESTION CATEGORIES:
- direct_solution: Provides immediate answers/information for identified gaps
- timing_optimization: Schedules tasks based on behavioral timing patterns
- workflow_improvement: Specific tool/process improvements with implementation details  
- content_completion: Fills in missing information or provides needed resources
- proactive_solution: Anticipates future needs with ready solutions

Return JSON in this exact format:
{{
  "suggestions": [
    {{
      "title": "Direct, solution-focused title (max 60 chars)",
      "description": "Detailed solution with specific information, links, answers, or steps (max 300 chars)",
      "category": "direct_solution|timing_optimization|workflow_improvement|content_completion|proactive_solution",
      "rationale": "Evidence-based reasoning connecting behavioral patterns to the provided solution (max 200 chars)",
      "priority": "high|medium|low"
    }},
    ...
  ]
}}

EXAMPLES OF SOLUTION-FIRST SUGGESTIONS:
❌ "Research DECA terminology for missing prompts"
✅ "DECA integration completes as: 'Integrates into Career and Technical Education (CTE) Instruction' - add this to your quiz review"

❌ "Look up productivity techniques for late-night work"  
✅ "Since you work past 11 PM, use the Pomodoro Technique: 25min work, 5min break. Blue light filters after 10 PM improve focus"

❌ "Find documentation tools for your project"
✅ "Use Notion templates for educational content: Create sections for Questions, Answers, Sources. Template link: notion.so/templates/education"""

UTILITY_SCORING_PROMPT = """You are a suggestion utility evaluator. Score each suggestion based on expected value for the user.

USER CONTEXT: {user_context}

SUGGESTIONS TO SCORE:
{suggestions_json}

For each suggestion, provide scores (1-10 scale):
- benefit: Expected positive impact if implemented
- false_positive_cost: Harm if suggestion is wrong/irrelevant  
- false_negative_cost: Opportunity cost if user ignores good suggestion
- decay: How long the suggestion stays relevant (10=weeks, 1=minutes)
- probability_useful: Likelihood user finds this genuinely helpful (0.0-1.0)

Return JSON:
{{
  "scored_suggestions": [
    {{
      "index": 0,
      "benefit": 8.5,
      "false_positive_cost": 2.0,
      "false_negative_cost": 6.0,
      "decay": 7.0,
      "probability_useful": 0.85,
      "probability_false_positive": 0.15,
      "probability_false_negative": 0.10
    }},
    ...
  ]
}}"""


class GumboEngine:
    """
    Production-grade Gumbo suggestion engine.
    
    Implements the complete Gumbo algorithm with error handling,
    rate limiting, and real-time delivery capabilities.
    """
    
    def __init__(self):
        """Initialize the Gumbo engine."""
        self.rate_limiter = None
        self.ai_client = None
        self._active_sse_connections: set = set()
        self._suggestion_metrics = {
            "total_suggestions": 0,
            "total_batches": 0,
            "total_processing_time": 0.0,
            "last_batch_at": None,
            "rate_limit_hits": 0
        }

        # Session factory provided by controller at startup
        self._session_factory = None

        # Engine lifecycle
        self._started = False
        self._startup_time = None

        logger.info("GumboEngine initialized")

    def set_db_session_factory(self, session_factory) -> None:
        """Set the SQLAlchemy async session factory used to persist suggestions.

        Must be called during application startup (before any suggestions are
        generated) so the engine can write to the same database as the gum
        instance running in the controller.

        Args:
            session_factory: The async_sessionmaker returned by init_db.
        """
        self._session_factory = session_factory
        logger.info("GumboEngine session factory registered")
    
    async def start(self):
        """Start the Gumbo engine with proper initialization."""
        if self._started:
            return
        
        try:
            # Initialize rate limiter
            self.rate_limiter = await get_rate_limiter()
            
            # Initialize AI client
            self.ai_client = await get_unified_client()
            
            self._started = True
            self._startup_time = datetime.now(timezone.utc)
            
            logger.info("GumboEngine started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start GumboEngine: {e}")
            raise
    
    async def stop(self):
        """Stop the Gumbo engine with proper cleanup."""
        if not self._started:
            return
        
        try:
            # Close all SSE connections
            for connection in list(self._active_sse_connections):
                await self._close_sse_connection(connection)
            
            # Shutdown rate limiter
            if self.rate_limiter:
                await self.rate_limiter.stop()
            
            self._started = False
            logger.info("GumboEngine stopped successfully")
            
        except Exception as e:
            logger.error(f"Error stopping GumboEngine: {e}")
    
    async def trigger_gumbo_suggestions(
        self, 
        proposition_id: int, 
        session: AsyncSession
    ) -> Optional[SuggestionBatch]:
        """
        Main Gumbo algorithm entry point.
        
        Triggered when a new high-confidence proposition is created.
        Implements the complete Gumbo flow with error handling.
        
        Args:
            proposition_id: ID of the trigger proposition
            session: Database session
            
        Returns:
            SuggestionBatch if successful, None if failed/rate limited
        """
        if not self._started:
            await self.start()
        
        start_time = time.time()
        batch_id = str(uuid.uuid4())
        
        try:
            logger.info(
                f"[GUMBO] ---- Suggestion pipeline START (proposition_id={proposition_id}) ----"
            )

            # Step 1: Rate limiting check
            if not await self.rate_limiter.can_generate_suggestions():
                wait_time = await self.rate_limiter.get_wait_time()
                logger.info(
                    f"[GUMBO] Step 1 — Rate limited. Next batch available in {wait_time:.1f}s"
                )
                
                self._suggestion_metrics["rate_limit_hits"] += 1
                
                # Notify SSE clients about rate limiting
                await self._broadcast_sse_event(SSEEvent(
                    event=SSEEventType.RATE_LIMITED,
                    data={
                        "wait_time_seconds": wait_time,
                        "next_available_at": (datetime.now(timezone.utc) + 
                                            timedelta(seconds=wait_time)).isoformat(),
                        "message": f"Suggestion generation rate limited. Next batch available in {wait_time:.0f} seconds."
                    }
                ))
                
                return None
            
            # Step 2: Retrieve trigger proposition
            trigger_prop = await self._get_trigger_proposition(session, proposition_id)
            if not trigger_prop:
                logger.error(
                    f"[GUMBO] Step 2 — Trigger proposition {proposition_id} not found in DB"
                )
                return None

            logger.info(
                f"[GUMBO] Step 2 — Trigger proposition loaded: "
                f"confidence={trigger_prop.confidence} | "
                f"{trigger_prop.text[:100].replace(chr(10), ' ')}..."
            )

            # Step 3: Contextual retrieval
            logger.info(f"[GUMBO] Step 3 — Retrieving contextual propositions from DB...")
            context_result = await self._contextual_retrieval(session, trigger_prop)
            logger.info(
                f"[GUMBO] Step 3 — Context: {len(context_result.related_propositions)} related propositions, "
                f"{len(context_result.recent_observations)} recent observations"
            )

            # Step 4: Multi-candidate generation
            logger.info(
                f"[GUMBO] Step 4 — Calling LLM "
                f"(SUGGEST_MODEL={os.getenv('SUGGEST_MODEL', 'default')}) "
                f"to generate suggestion candidates..."
            )
            suggestions = await self._generate_suggestion_candidates(trigger_prop, context_result)
            logger.info(f"[GUMBO] Step 4 — LLM returned {len(suggestions)} suggestion candidates")
            for idx, s in enumerate(suggestions):
                preview = s.content[:100].replace("\n", " ") if hasattr(s, "content") else str(s)[:100]
                logger.info(f"[GUMBO]   Candidate {idx + 1}/{len(suggestions)}: {preview}...")

            # Step 5: Mixed-initiative filtering (utility scoring)
            logger.info(f"[GUMBO] Step 5 — Scoring {len(suggestions)} candidates for utility...")
            scored_suggestions = await self._score_suggestions(trigger_prop, suggestions, context_result)
            logger.info(f"[GUMBO] Step 5 — {len(scored_suggestions)} suggestions passed scoring")
            for idx, s in enumerate(scored_suggestions):
                score_info = f"utility={s.utility_score:.2f}" if hasattr(s, "utility_score") else ""
                preview = s.content[:80].replace("\n", " ") if hasattr(s, "content") else str(s)[:80]
                logger.info(f"[GUMBO]   Scored {idx + 1}/{len(scored_suggestions)}: {score_info} | {preview}...")

            # Step 6: Create suggestion batch
            processing_time = time.time() - start_time
            logger.info(
                f"[GUMBO] Step 6 — Building suggestion batch "
                f"({len(scored_suggestions)} suggestions, batch_id={batch_id})"
            )
            batch = SuggestionBatch(
                suggestions=scored_suggestions,
                trigger_proposition_id=proposition_id,
                generated_at=datetime.now(timezone.utc),
                processing_time_seconds=processing_time,
                context_propositions_used=len(context_result.related_propositions),
                batch_id=batch_id
            )
            
            # Update metrics
            self._update_metrics(batch)

            # Step 7: Persist to database
            logger.info(
                f"[GUMBO] Step 7 — Saving {len(batch.suggestions)} suggestions "
                f"(batch_id={batch_id}) to database..."
            )
            await self._broadcast_suggestion_batch(batch)
            logger.info(
                f"[GUMBO] Pipeline complete for proposition {proposition_id} "
                f"in {processing_time:.2f}s — {len(batch.suggestions)} suggestions saved"
            )
            return batch
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"❌ Gumbo failed for proposition {proposition_id} after {processing_time:.2f}s: {e}")
            
            # Notify SSE clients about error
            await self._broadcast_sse_event(SSEEvent(
                event=SSEEventType.ERROR,
                data={
                    "error_type": "suggestion_generation_failed",
                    "message": f"Failed to generate suggestions: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "proposition_id": proposition_id
                }
            ))
            
            return None
    
    async def _get_trigger_proposition(
        self, 
        session: AsyncSession, 
        proposition_id: int
    ) -> Optional[Proposition]:
        """Retrieve the trigger proposition from database."""
        try:
            stmt = select(Proposition).where(Proposition.id == proposition_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Failed to retrieve trigger proposition {proposition_id}: {e}")
            return None
    
    async def _contextual_retrieval(
        self, 
        session: AsyncSession, 
        trigger_prop: Proposition
    ) -> ContextRetrievalResult:
        """
        Step 2: Contextual Retrieval
        
        Use LLM to generate semantic search query, then retrieve related propositions.
        """
        start_time = time.time()
        
        try:
            # Generate semantic search query using LLM
            query_prompt = CONTEXTUAL_RETRIEVAL_PROMPT.format(
                trigger_text=trigger_prop.text,
                trigger_reasoning=trigger_prop.reasoning[:300]  # Truncate for prompt size
            )
            
            # Call LLM for semantic query generation
            semantic_query = await asyncio.wait_for(
                self.ai_client.text_completion(
                    [{"role": "user", "content": query_prompt}],
                    max_tokens=50,
                    model=os.getenv("SUGGEST_MODEL"),
                ),
                timeout=30.0,
            )
            
            semantic_query = semantic_query.strip().strip('"').strip("'")
            logger.info(f"🔍 Generated semantic query: '{semantic_query}'")
            
            # Search for related propositions using BM25
            search_results = await search_propositions_bm25(
                session,
                semantic_query,
                mode="OR",
                limit=20,
                include_observations=False,
                enable_mmr=True,
                enable_decay=True
            )
            
            # Convert to contextual propositions
            related_propositions = []
            for prop, score in search_results:
                if prop.id != trigger_prop.id:  # Exclude trigger proposition
                    related_propositions.append(ContextualProposition(
                        id=prop.id,
                        text=prop.text,
                        reasoning=prop.reasoning,
                        confidence=prop.confidence or 0.0,
                        created_at=prop.created_at,
                        similarity_score=float(score)
                    ))
            
            # Limit to top 10 for context management
            related_propositions = related_propositions[:10]
            
            retrieval_time = time.time() - start_time
            
            logger.info(f"📋 Retrieved {len(related_propositions)} related propositions in {retrieval_time:.2f}s")
            
            return ContextRetrievalResult(
                related_propositions=related_propositions,
                total_found=len(search_results),
                retrieval_time_seconds=retrieval_time,
                semantic_query=semantic_query
            )
            
        except Exception as e:
            logger.error(f"Contextual retrieval failed: {e}")
            # Return empty result on failure
            return ContextRetrievalResult(
                related_propositions=[],
                total_found=0,
                retrieval_time_seconds=time.time() - start_time,
                semantic_query="fallback_query"
            )
    
    async def _generate_suggestion_candidates(
        self, 
        trigger_prop: Proposition, 
        context_result: ContextRetrievalResult
    ) -> List[Dict[str, Any]]:
        """
        Step 3: Multi-Candidate Generation
        
        Generate 5 suggestion candidates using trigger proposition and context.
        """
        try:
            # Prepare context for LLM
            related_context = ""
            for prop in context_result.related_propositions[:5]:  # Top 5 for context
                related_context += f"- {prop.text} (confidence: {prop.confidence:.1f}, similarity: {prop.similarity_score:.2f})\n"
            
            if not related_context:
                related_context = "No directly related behavioral patterns found."
            
            # Generate suggestion candidates
            generation_prompt = MULTI_CANDIDATE_GENERATION_PROMPT.format(
                trigger_text=trigger_prop.text,
                related_context=related_context
            )
            
            # Call LLM for suggestion generation
            response = await asyncio.wait_for(
                self.ai_client.text_completion(
                    [{"role": "user", "content": generation_prompt}],
                    max_tokens=1000,
                    model=os.getenv("SUGGEST_MODEL"),
                ),
                timeout=30.0,
            )
            
            # Parse JSON response
            suggestions_data = self._parse_json_response(response, "suggestions")
            suggestions = suggestions_data.get("suggestions", [])
            
            if len(suggestions) != 5:
                logger.warning(f"Expected 5 suggestions, got {len(suggestions)}")
            
            logger.info(f"💡 Generated {len(suggestions)} suggestion candidates")
            return suggestions
            
        except Exception as e:
            logger.error(f"Suggestion generation failed: {e}")
            # Return fallback suggestions
            return [
                {
                    "title": "Review recent behavioral patterns",
                    "description": "Take a moment to review your recent activity patterns for optimization opportunities.",
                    "category": "productivity",
                    "rationale": "Fallback suggestion due to generation error",
                    "priority": "medium"
                }
            ]
    
    async def _score_suggestions(
        self, 
        trigger_prop: Proposition, 
        suggestions: List[Dict[str, Any]], 
        context_result: ContextRetrievalResult
    ) -> List[SuggestionData]:
        """
        Step 4: Mixed-Initiative Filtering
        
        Score suggestions using Expected Utility formula and return filtered results.
        """
        try:
            if not suggestions:
                return []
            
            # Prepare context for utility scoring
            user_context = f"Recent behavior: {trigger_prop.text}"
            if context_result.related_propositions:
                user_context += f"\nRelated patterns: {len(context_result.related_propositions)} behavioral insights"
            
            # Call LLM for utility scoring
            scoring_prompt = UTILITY_SCORING_PROMPT.format(
                user_context=user_context,
                suggestions_json=json.dumps(suggestions, indent=2)
            )
            
            response = await asyncio.wait_for(
                self.ai_client.text_completion(
                    [{"role": "user", "content": scoring_prompt}],
                    max_tokens=800,
                    model=os.getenv("SUGGEST_MODEL"),
                ),
                timeout=30.0,
            )
            
            # Parse scoring response
            scoring_data = self._parse_json_response(response, "scored_suggestions")
            scored_items = scoring_data.get("scored_suggestions", [])
            
            # Create final suggestion list with utility scores
            final_suggestions = []
            
            for i, suggestion in enumerate(suggestions):
                # Find corresponding score
                score_data = None
                for scored in scored_items:
                    if scored.get("index") == i:
                        score_data = scored
                        break
                
                if score_data:
                    # Calculate Expected Utility using the research formula
                    # EU = (Benefit × P_useful) - (FP_Cost × P_false_positive) - (FN_Cost × P_false_negative) × Decay_factor
                    benefit = score_data.get("benefit", 5.0)
                    fp_cost = score_data.get("false_positive_cost", 3.0)
                    fn_cost = score_data.get("false_negative_cost", 4.0)
                    decay = score_data.get("decay", 5.0)
                    p_useful = score_data.get("probability_useful", 0.5)
                    p_fp = score_data.get("probability_false_positive", 0.2)
                    p_fn = score_data.get("probability_false_negative", 0.3)
                    
                    # Expected Utility calculation
                    expected_utility = (
                        (benefit * p_useful) - 
                        (fp_cost * p_fp) - 
                        (fn_cost * p_fn)
                    ) * (decay / 10.0)  # Normalize decay to 0-1 range
                    
                    utility_scores = UtilityScores(
                        benefit=benefit,
                        false_positive_cost=fp_cost,
                        false_negative_cost=fn_cost,
                        decay=decay,
                        probability_useful=p_useful,
                        probability_false_positive=p_fp,
                        probability_false_negative=p_fn
                    )
                else:
                    # Fallback scoring
                    expected_utility = 5.0
                    utility_scores = None
                    p_useful = 0.5
                
                # Create final suggestion
                final_suggestion = SuggestionData(
                    title=suggestion.get("title", "Untitled Suggestion")[:200],
                    description=suggestion.get("description", "No description provided")[:1000],
                    probability_useful=p_useful,
                    rationale=suggestion.get("rationale", "No rationale provided")[:500],
                    category=suggestion.get("category", "general")[:100],
                    utility_scores=utility_scores,
                    expected_utility=expected_utility
                )
                
                final_suggestions.append(final_suggestion)
            
            # Sort by expected utility (highest first) and limit to top 5
            final_suggestions.sort(key=lambda x: x.expected_utility or 0, reverse=True)
            final_suggestions = final_suggestions[:5]
            
            logger.info(f"📊 Scored {len(final_suggestions)} suggestions, top utility: {final_suggestions[0].expected_utility:.2f}")
            
            return final_suggestions
            
        except Exception as e:
            logger.error(f"Suggestion scoring failed: {e}")
            
            # Create fallback scored suggestions
            fallback_suggestions = []
            for i, suggestion in enumerate(suggestions[:5]):
                fallback_suggestion = SuggestionData(
                    title=suggestion.get("title", f"Suggestion {i+1}")[:200],
                    description=suggestion.get("description", "Fallback suggestion")[:1000],
                    probability_useful=0.5,
                    rationale=suggestion.get("rationale", "Fallback rationale")[:500],
                    category=suggestion.get("category", "general")[:100],
                    expected_utility=5.0
                )
                fallback_suggestions.append(fallback_suggestion)
            
            return fallback_suggestions
    
    def _parse_json_response(self, response: str, expected_key: str) -> Dict[str, Any]:
        """Parse JSON response from LLM with error handling."""
        try:
            # Clean up the response
            response = response.strip()
            
            # Try to find JSON in the response
            start_idx = response.find('{')
            end_idx = response.rfind('}')
            
            if start_idx >= 0 and end_idx >= 0:
                json_str = response[start_idx:end_idx+1]
                data = json.loads(json_str)
                
                if expected_key in data:
                    return data
                else:
                    logger.warning(f"Expected key '{expected_key}' not found in response")
                    return {expected_key: []}
            else:
                logger.error("No valid JSON found in LLM response")
                return {expected_key: []}
                
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            return {expected_key: []}
        except Exception as e:
            logger.error(f"Unexpected error parsing response: {e}")
            return {expected_key: []}
    
    def _update_metrics(self, batch: SuggestionBatch):
        """Update internal metrics tracking."""
        self._suggestion_metrics["total_suggestions"] += len(batch.suggestions)
        self._suggestion_metrics["total_batches"] += 1
        self._suggestion_metrics["total_processing_time"] += batch.processing_time_seconds
        self._suggestion_metrics["last_batch_at"] = batch.generated_at
    
    async def _broadcast_suggestion_batch(self, batch: SuggestionBatch):
        """Broadcast suggestion batch to all connected SSE clients."""
        logger.info(f"🚨 _broadcast_suggestion_batch called with {len(batch.suggestions)} suggestions")
        event = SSEEvent(
            event=SSEEventType.SUGGESTION_BATCH,
            data=batch.dict()
        )
        logger.info(f"🚨 Created SSE event, calling _broadcast_sse_event")
        await self._broadcast_sse_event(event)
        logger.info(f"🚨 _broadcast_sse_event completed")
    
    async def _broadcast_sse_event(self, event: SSEEvent):
        """Persist suggestions to the database using the shared session factory."""
        suggestions_list = event.data.get("suggestions", [])
        logger.info(f"Saving {len(suggestions_list)} suggestions to database")

        if self._session_factory is None:
            logger.error(
                "No session factory set on GumboEngine — suggestions cannot be saved. "
                "Ensure set_db_session_factory() is called during startup."
            )
            return

        try:
            from gum.models import Suggestion, Proposition

            async with self._session_factory() as session:
                async with session.begin():
                    suggestions_saved = 0
                    batch_id = f"gumbo_{int(time.time())}"
                    trigger_proposition_id = event.data.get("trigger_proposition_id")
                    processing_time = event.data.get("processing_time_seconds")
                    context_count = event.data.get("context_propositions_used")
                    generation_model = os.getenv("SUGGEST_MODEL")

                    # Fetch trigger proposition once so we can snapshot its
                    # text/confidence/reasoning on every suggestion row.
                    trigger_prop = None
                    if trigger_proposition_id is not None:
                        trigger_prop = await session.get(Proposition, trigger_proposition_id)
                        if trigger_prop is None:
                            logger.warning(
                                f"Trigger proposition {trigger_proposition_id} not found "
                                f"— snapshot fields will be NULL"
                            )

                    for suggestion_data in suggestions_list:
                        suggestion = Suggestion(
                            title=suggestion_data.get("title", "Untitled")[:200],
                            description=suggestion_data.get("description", "")[:1000],
                            category=suggestion_data.get("category", "general")[:100],
                            rationale=suggestion_data.get("rationale", "")[:500],
                            expected_utility=suggestion_data.get("expected_utility", 5.0),
                            probability_useful=suggestion_data.get("probability_useful", 0.7),
                            trigger_proposition_id=trigger_proposition_id,
                            batch_id=batch_id,
                            delivered=False,
                            # Snapshot fields
                            trigger_proposition_text=(
                                trigger_prop.text if trigger_prop else None
                            ),
                            trigger_proposition_confidence=(
                                trigger_prop.confidence if trigger_prop else None
                            ),
                            trigger_proposition_reasoning=(
                                trigger_prop.reasoning if trigger_prop else None
                            ),
                            # Batch metadata
                            processing_time_seconds=processing_time,
                            context_propositions_count=context_count,
                            generation_model=generation_model,
                        )
                        session.add(suggestion)
                        suggestions_saved += 1

            logger.info(f"Saved {suggestions_saved} suggestions to database (batch: {batch_id})")

        except Exception as e:
            import traceback
            logger.error(f"Failed to save suggestions: {e}")
            logger.error(traceback.format_exc())
    
    async def register_sse_connection(self, connection):
        """Register a new SSE connection."""
        self._active_sse_connections.add(connection)
        logger.info(f"SSE connection registered, total: {len(self._active_sse_connections)}")
    
    async def _close_sse_connection(self, connection):
        """Close and remove an SSE connection."""
        self._active_sse_connections.discard(connection)
        logger.info(f"SSE connection closed, remaining: {len(self._active_sse_connections)}")
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get current engine health status."""
        if not self._started:
            return {
                "status": "stopped",
                "uptime_seconds": 0,
                "metrics": self._suggestion_metrics,
                "rate_limit_status": None
            }
        
        uptime = (datetime.now(timezone.utc) - self._startup_time).total_seconds()
        
        # Calculate average processing time
        avg_processing_time = 0.0
        if self._suggestion_metrics["total_batches"] > 0:
            avg_processing_time = (
                self._suggestion_metrics["total_processing_time"] / 
                self._suggestion_metrics["total_batches"]
            )
        
        status = "healthy"
        if avg_processing_time > 10.0:  # Slow processing
            status = "degraded"
        
        return {
            "status": status,
            "uptime_seconds": uptime,
            "metrics": {
                **self._suggestion_metrics,
                "average_processing_time_seconds": avg_processing_time,
                "active_sse_connections": len(self._active_sse_connections)
            },
            "rate_limit_status": self.rate_limiter.get_status() if self.rate_limiter else None
        }


# Global engine instance (singleton pattern)
_global_engine: Optional[GumboEngine] = None


async def get_gumbo_engine() -> GumboEngine:
    """
    Get the global Gumbo engine instance.
    
    Returns:
        Initialized GumboEngine instance
    """
    global _global_engine
    
    if _global_engine is None:
        _global_engine = GumboEngine()
        await _global_engine.start()
    
    return _global_engine


async def trigger_gumbo_suggestions(proposition_id: int, session: AsyncSession) -> Optional[SuggestionBatch]:
    """
    Convenience function to trigger Gumbo suggestions.
    
    This is the main entry point called from gum/gum.py when a high-confidence
    proposition is created.
    """
    try:
        engine = await get_gumbo_engine()
        return await engine.trigger_gumbo_suggestions(proposition_id, session)
    except Exception as e:
        logger.error(f"Failed to trigger Gumbo suggestions: {e}")
        return None


async def shutdown_gumbo_engine():
    """Shutdown the global Gumbo engine (for cleanup)."""
    global _global_engine
    
    if _global_engine is not None:
        await _global_engine.stop()
        _global_engine = None
        logger.info("Global GumboEngine shutdown complete")
