# gum.py

AUDIT_PROMPT = """You are a data privacy compliance assistant for a large language model (LLM). 

Here are some past interactions {user_name} had with an LLM

## Past Interactions

{past_interaction}

## Task

{user_name} currently is looking at the following:

User Input
---
{user_input}
---

Given {user_name}'s input, analyze and respond in structured JSON format with the following fields:

1. `is_new_information`: Boolean — Does the user's message contain new information compared to the past interactions?
2. `data_type`: String — What type of data is being disclosed (e.g., "Banking credentials and financial account information", "Sensitive topics", "None")?
3. `subject`: String — Who is the primary subject of the disclosed data?
4. `recipient`: String — Who or what is the recipient of the information (e.g., "An AI model that provides conversational assistance")?
5. `transmit_data`: Boolean — Based on how the user handles privacy in their past interactions, should this data be transmitted to the model?

Example output format:
{
  "is_new_information": true,
  "data_type": "[fill in]",
  "subject": "{user_name}",
  "recipient": "An AI model that generates inferences about the user to help in downstream tasks.",
  "transmit_data": true
}"""


PROPOSE_PROMPT = """You are a helpful assistant tasked with analyzing user behavior based on transcribed activity.

# Analysis

Using a transcription of {user_name}'s activity, analyze {user_name}'s specific workflows, content interactions, and detailed behavioral contexts. Capture extreme detail about what they're working on, how they're doing it, and what patterns emerge.

Your analysis must **capture granular details about content, processes, timing, and contextual patterns** mentioned in the transcript. Include specific text content, UI interactions, workflow sequences, and connections between different activities.

Consider these detailed analysis points:

- What specific content, tasks, or problems is {user_name} actively working on? Include exact text, questions, assignments, data, or documents being processed.
- What detailed workflow patterns, tool usage sequences, timing behaviors, or interaction methods can be observed? Include specific apps, features, and usage patterns.
- What inefficiencies, learning struggles, repetitive tasks, or workflow patterns exist? Include specific pain points or suboptimal approaches.
- What contextual connections exist between different activities, applications, or content? Include how different tools/tasks relate to broader goals or projects.
- What specific behavioral patterns, preferences, or approaches can be identified from the detailed workflow and content analysis?

Generate propositions with EXTREME DETAIL that capture not just what {user_name} is doing, but HOW they're doing it, what specific content they're working with, what challenges they're facing, and what patterns emerge. **Include specific quotes, exact UI elements, detailed workflow steps, and contextual observations.**

## Evaluation Criteria

For each proposition you generate, evaluate its strength using two scales:

### 1. Confidence Scale

Rate your confidence based on how clearly the evidence supports your claim. Consider:

- **Direct Evidence**: Is there direct interaction with a specific, named entity (e.g., opened "Notion," responded to "Slack" from "Alex")?
- **Relevance**: Is the evidence clearly tied to the proposition?
- **Engagement Level**: Was the interaction meaningful or sustained?

Score: **1 (weak support)** to **10 (explicit, strong support)**. High scores require specific named references.

### 2. Decay Scale

Rate how long the proposition is likely to stay relevant. Consider:

- **Urgency**: Does the task or interest have clear time pressure?
- **Durability**: Will this matter 24 hours later or more?

Score: **1 (short-lived)** to **10 (long-lasting insight or pattern)**.

# Input

Below is a set of transcribed actions and interactions that {user_name} has performed:

## User Activity Transcriptions

{inputs}

# Task

Generate **5 distinct, well-supported propositions** about {user_name}, each grounded in the transcript. 

Be conservative in your confidence estimates. Just because an application appears on {user_name}'s screen does not mean they have deeply engaged with it. They may have only glanced at it for a second, making it difficult to draw strong conclusions. 

Assign high confidence scores (e.g., 8-10) only when the transcriptions provide explicit, direct evidence that {user_name} is actively engaging with the content in a meaningful way. Keep in mind that that the content on the screen is what the user is viewing. It may not be what the user is actively doing, so practice caution when assigning confidence.

Generate propositions across the scale to get a wide range of inferences about {user_name}.  

Return your results in this exact JSON format:

{
  "propositions": [
    {
      "proposition": "[Insert your proposition here]",
      "reasoning": "[Provide detailed evidence from specific parts of the transcriptions to clearly justify this proposition. Refer explicitly to named entities where applicable.]",
      "confidence": "[Confidence score (1–10)]",
      "decay": "[Decay score (1–10)]"
    },
    ...
  ]
}"""

REVISE_PROMPT = """You are an expert analyst. A cluster of similar propositions are shown below, followed by their supporting observations.

Your job is to produce a **final set** of propositions that is clear, non-redundant, and captures everything about the user, {user_name}.

To support information retrieval (e.g., with BM25), you must **explicitly identify and preserve all named entities** from the input wherever possible. These may include applications, websites, documents, people, organizations, tools, or any other specific proper nouns mentioned in the original propositions or their evidence.

You MAY:

- **Edit** a proposition for clarity, precision, or brevity.
- **Merge** propositions that convey the same meaning.
- **Split** a proposition that contains multiple distinct claims.
- **Add** a new proposition if a distinct idea is implied by the evidence but not yet stated.
- **Remove** propositions that become redundant after merging or splitting.

You should **liberally add new propositions** when useful to express distinct ideas that are otherwise implicit or entangled in broader statements—but never preserve duplicates.

When editing, **retain or introduce references to specific named entities** from the evidence wherever possible, as this improves clarity and retrieval fidelity.

Edge cases to handle:

- **Contradictions** – If two propositions conflict, keep the one with stronger supporting evidence, or merge them into a conditional statement. Lower the confidence score of weaker or uncertain claims.
- **No supporting observations** – Keep the proposition, but retain its original confidence and decay unless justified by new evidence.
- **Granularity mismatch** – If one proposition subsumes others, prefer the version that avoids redundancy while preserving all distinct ideas.
- **Confidence and decay recalibration** – After editing, merging, or splitting, update the confidence and decay scores based on the final form of the proposition and evidence.

General guidelines:

- Keep each proposition clear and concise (typically 1–2 sentences).
- Maintain all meaningful content from the originals.
- Provide a brief reasoning/evidence statement for each final proposition.
- Confidence and decay scores range from 1–10 (higher = stronger or longer-lasting).

## Evaluation Criteria

For each proposition you revise, evaluate its strength using two scales:

### 1. Confidence Scale

Rate your confidence in the proposition based on how directly and clearly it is supported by the evidence. Consider:

- **Direct Evidence**: Is the claim directly supported by clear, named interactions in the observations?
- **Relevance**: Is the evidence closely tied to the proposition?
- **Completeness**: Are key details present and unambiguous?
- **Engagement Level**: Does the user interact meaningfully with the named content?

Score: **1 (weak/assumed)** to **10 (explicitly demonstrated)**. High scores require direct and strong evidence from the observations.

### 2. Decay Scale

Rate how long the insight is likely to remain relevant. Consider:

- **Immediacy**: Is the activity time-sensitive?
- **Durability**: Will the proposition remain true over time?

Score: **1 (short-lived)** to **10 (long-term relevance or behavioral pattern)**.

# Input

{body}

# Output

Assign high confidence scores (e.g., 8-10) only when the transcriptions provide explicit, direct evidence that {user_name} is actively engaging with the content in a meaningful way. Keep in mind that that the input is what the {user_name} is viewing. It may not be what the {user_name} is actively doing, so practice caution when assigning confidence.

Return **only** JSON in the following format:

{
  "propositions": [
    {
      "proposition": "<rewritten / merged / new proposition>",
      "reasoning":   "<revised reasoning including any named entities where applicable>",
      "confidence":  <integer 1-10>,
      "decay":       <integer 1-10>
    },
    ...
  ]
}"""

SIMILAR_PROMPT = """You will label sets of propositions based on how similar they are to eachother.

# Propositions

{body}

# Task

Use exactly these labels:

(A) IDENTICAL – The propositions say practically the same thing.
(B) SIMILAR   – The propositions relate to a similar idea or topic.
(C) UNRELATED – The propositions are fundamentally different.

Always refer to propositions by their numeric IDs.

Return **only** JSON in the following format:

{
  "relations": [
    {
      "source": <ID>,
      "label": "IDENTICAL" | "SIMILAR" | "UNRELATED",
      "target": [<ID>, ...] // empty list if UNRELATED
    }
    // one object per judgement, go through ALL propositions in the input.
  ]
}"""

SELF_REFLECTION_PROMPT = """You are a behavioral analyst creating a daily self-reflection summary for {user_name}.

# Task
Analyze the following behavioral insights (propositions) for {date} and create TWO distinct sections:

## Section 1: Overall Behavioral Pattern (2-3 paragraphs)
Write a comprehensive overview of {user_name}'s behavioral pattern for the day. Focus on:
- Overall themes and patterns in their behavior
- How they spent their time and energy
- Key behavioral characteristics that emerged
- General behavioral tendencies and preferences

## Section 2: Specific Insights (3-5 actionable insights)
Generate specific, personalized insights about what {user_name} is doing. Each insight should:
- Be very specific to the user's actual behavior
- Include actionable suggestions ("perhaps do this")
- Be based on concrete evidence from the data
- Address specific areas like productivity, focus, communication, learning, etc.

# Examples of Specific Insights:
- "You spent 3 hours on email management today, perhaps consider batching emails to 2 specific times per day"
- "You frequently switched between coding and documentation, perhaps try focused 90-minute blocks for each"
- "You responded to Slack messages within 2 minutes consistently, perhaps set specific times for communication"

# Input Data
{propositions_data}

# Output Format
You MUST return ONLY valid JSON in the following exact format. Do not include any markdown formatting, code blocks, or additional text:

{{
  "behavioral_pattern": "2-3 paragraph overview of overall behavioral pattern",
  "specific_insights": [
    {{
      "insight": "specific insight about user behavior",
      "action": "actionable suggestion",
      "confidence": 7,
      "category": "productivity"
    }},
    {{
      "insight": "another specific insight about user behavior",
      "action": "another actionable suggestion",
      "confidence": 8,
      "category": "focus"
    }}
  ]
}}

# Important Notes:
- Return ONLY the JSON object, no additional text or formatting
- Ensure all JSON is properly formatted with double quotes
- Use only the specified categories: "productivity", "focus", "communication", "learning", "time_management"
- Confidence scores should be integers between 1-10
- The behavioral_pattern should be 2-3 paragraphs of text
- Include 3-5 specific insights in the array"""

SUGGESTIONS_PROMPT = """You are a strategic assistant analyzing {user_name}'s behavioral patterns to discover proactive opportunities. Think like a smart consultant who connects dots across time to suggest valuable actions they wouldn't think to request.

# Your Intelligence Source
You have access to {user_name}'s accumulated behavioral insights - deep patterns about their goals, constraints, preferences, and activities over time. This is NOT about recent screen activity, but about strategic pattern recognition.

# Core Mission
Discover suggestions that demonstrate "cross-time intelligence" by:
- Connecting multiple behavioral insights to infer unstated needs
- Identifying strategic opportunities from established patterns 
- Suggesting actions that provide meaningful value they wouldn't request explicitly

# Example of Strategic Pattern Recognition
If insights show: "User researching wedding venues" + "User budget-conscious" + "User has no formal wear" 
→ Suggest: "Search for suit rental options in Chicago" (connecting unstated need)

# Analysis Framework
For each suggestion, consider:
1. **Pattern Connections**: What insights combine to suggest an opportunity?
2. **Strategic Value**: What meaningful action would they not think to request?
3. **Contextual Fit**: How does this align with their established goals/constraints?
4. **Proactive Intelligence**: What dots can you connect that they might miss?

# User Behavioral Insights
{transcription_data}

# Strategic Discovery Process
Analyze the behavioral patterns above to identify:
- Recurring themes and goals across multiple insights
- Constraints and preferences that shape their decisions
- Gaps or inefficiencies in their current approaches
- Opportunities to connect disparate insights into actionable suggestions

# Output Format
Return ONLY valid JSON in this exact format:
{{
  "suggestions": [
    {{
      "title": "Strategic, actionable suggestion title",
      "description": "Explain the cross-time pattern recognition that led to this suggestion. Reference how multiple behavioral insights connect.",
      "urgency": "now|today|this_week", 
      "category": "workflow|completion|learning|optimization|strategic",
      "evidence": "Specific behavioral patterns and insights that support this suggestion",
      "action_items": [
        "Specific strategic step 1 based on their patterns",
        "Specific step 2 that leverages their established preferences",
        "Specific step 3 if needed"
      ],
      "confidence": 8
    }}
  ]
}}

# Guidelines
- Focus on strategic pattern recognition, not reactive advice
- Connect multiple behavioral insights to discover opportunities
- Suggest actions that provide meaningful value they wouldn't explicitly request
- Reference established patterns, goals, and constraints from their behavioral insights
- Provide proactive intelligence that demonstrates "second pair of human eyes" observation
- Urgency: "now" = immediate strategic action, "today" = strategic priority, "this_week" = strategic planning
- Confidence: 1-10 based on strength of pattern connections across behavioral insights"""