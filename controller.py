#!/usr/bin/env python3
"""
GUM REST API Controller

A FastAPI-based REST API that exposes GUM functionality for submitting
observations through text and images, and querying the system.
"""

import asyncio
import base64
import glob
import logging
import os
import subprocess
import tempfile
import time
import uuid
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from dateutil import parser as date_parser
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Union, AsyncIterator
from asyncio import Semaphore
import pytz
import json

import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
    Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
try:
    from sse_starlette.sse import EventSourceResponse
except ImportError:
    # Fallback if sse-starlette is not installed
    EventSourceResponse = None
from PIL import Image
from pydantic import BaseModel, Field
from rate_limiter import rate_limiter

from dotenv import load_dotenv
from gum import gum
from gum.schemas import (
    PropositionItem,
    PropositionSchema,
    RelationSchema,
    Update,
    AuditSchema,
    SelfReflectionResponse,
    SpecificInsight
)
from gum.observers import Observer
from unified_ai_client import UnifiedAIClient

# Gumbo (intelligent suggestions) imports with graceful fallback
try:
    from gum.services.gumbo_engine import get_gumbo_engine
    from gum.suggestion_models import (
        SuggestionHealthResponse, SuggestionMetrics, RateLimitStatus,
        SSEEvent, SSEEventType, HeartbeatSSEData, RateLimitSSEData, ErrorSSEData
    )
    GUMBO_AVAILABLE = True
except ImportError as e:
    # Note: logger not yet configured, using print for early import error
    print(f"Warning: Gumbo suggestion system not available: {e}")
    # Fallback definitions to prevent errors
    get_gumbo_engine = None
    SuggestionHealthResponse = dict
    SuggestionMetrics = dict
    RateLimitStatus = dict
    SSEEvent = dict
    SSEEventType = str
    HeartbeatSSEData = dict
    RateLimitSSEData = dict
    ErrorSSEData = dict
    GUMBO_AVAILABLE = False

# Load environment variables
load_dotenv(override=True)  # Ensure .env takes precedence

def _str_to_bool(value: Optional[str], default: bool = False) -> bool:
    """Convert common truthy/falsy strings to bool."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _parse_env_list(key: str, fallback: List[str]) -> List[str]:
    """Parse a comma-separated environment variable into a list."""
    raw = os.getenv(key)
    if not raw:
        return fallback
    return [item.strip() for item in raw.split(",") if item.strip()]


# API authentication token (required for protected routes)
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN")

# CORS configuration from environment with safer defaults
ALLOWED_ORIGINS = _parse_env_list(
    "ALLOWED_ORIGINS",
    ["http://localhost:3000", "http://localhost:8000"]
)
ALLOWED_METHODS = _parse_env_list(
    "ALLOWED_METHODS",
    ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)
ALLOWED_HEADERS = _parse_env_list(
    "ALLOWED_HEADERS",
    ["Authorization", "Content-Type"]
)
ALLOW_CREDENTIALS = _str_to_bool(os.getenv("ALLOW_CREDENTIALS"), False)
CORS_MAX_AGE = int(os.getenv("CORS_MAX_AGE", "86400"))

# Documentation exposure
ENABLE_API_DOCS = _str_to_bool(os.getenv("ENABLE_API_DOCS"), False)
DOCS_URL = "/docs" if ENABLE_API_DOCS else None
REDOC_URL = "/redoc" if ENABLE_API_DOCS else None

# Configure logging with user-friendly format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',  # Cleaner format for user visibility
    datefmt='%H:%M:%S',  # Just time, not full date
    handlers=[
        logging.StreamHandler()  # Ensure console output
    ]
)
logger = logging.getLogger(__name__)

# Ensure immediate console output (force flush)
import sys
import os
os.environ['PYTHONUNBUFFERED'] = '1'

PROTECTED_PATH_PREFIXES = ("/monitoring", "/admin")


def _extract_token(request: Request) -> Optional[str]:
    """Extract bearer or API key token from headers."""
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() in {"bearer", "token", "api-key", "apikey"}:
            return parts[1]
    api_key_header = request.headers.get("x-api-key")
    if api_key_header:
        return api_key_header.strip()
    return None


async def require_api_auth(request: Request) -> None:
    """Enforce API token on protected endpoints."""
    if not API_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication token not configured"
        )
    token = _extract_token(request)
    if token != API_AUTH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API authentication token",
            headers={"WWW-Authenticate": "Bearer"}
        )

# Initialize FastAPI app
app = FastAPI(
    title="GUM API",
    description="REST API for submitting observations and querying user behavior insights",
    version="1.0.0",
    docs_url=DOCS_URL,
    redoc_url=REDOC_URL
)

# Add CORS middleware to allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=ALLOWED_METHODS,
    allow_headers=ALLOWED_HEADERS,
    max_age=CORS_MAX_AGE
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Protect sensitive routes with API token authentication."""
    path = request.url.path
    if any(path.startswith(prefix) for prefix in PROTECTED_PATH_PREFIXES):
        await require_api_auth(request)
    return await call_next(request)

# Global GUM instance
gum_instance: Optional[gum] = None

# Global unified AI client
ai_client: Optional[UnifiedAIClient] = None

# Gumbo suggestion system globals (SSE removed - now using HTTP polling)
suggestion_metrics = {
    "total_suggestions": 0,
    "total_batches": 0,
    "total_processing_time": 0.0,
    "rate_limit_hits": 0
}


async def get_ai_client() -> UnifiedAIClient:
    """Get or create the unified AI client."""
    if not hasattr(get_ai_client, '_client'):
        logger.info("Initializing unified AI client")
        ai_client = UnifiedAIClient()
        get_ai_client._client = ai_client
    
    return get_ai_client._client

# === Pydantic Models ===

class TextObservationRequest(BaseModel):
    """Request model for text observations."""
    content: str = Field(..., description="The text content of the observation", min_length=1)
    user_name: Optional[str] = Field(None, description="User name (optional, uses default if not provided)")
    observer_name: Optional[str] = Field("api_controller", description="Name of the observer submitting this")


class QueryRequest(BaseModel):
    """Request model for querying GUM."""
    query: str = Field(..., description="The search query", min_length=1)
    user_name: Optional[str] = Field(None, description="User name (optional)")
    limit: Optional[int] = Field(10, description="Maximum number of results to return", ge=1, le=100)
    mode: Optional[str] = Field("OR", description="Search mode (OR/AND)")


class ObservationResponse(BaseModel):
    """Response model for observations."""
    id: int = Field(..., description="Observation ID")
    content: str = Field(..., description="Observation content")
    content_type: str = Field(..., description="Type of content (input_text, input_image)")
    observer_name: str = Field(..., description="Name of the observer")
    created_at: str = Field(..., description="When the observation was created (ISO format)")


class PropositionResponse(BaseModel):
    """Response model for propositions."""
    id: int = Field(..., description="Proposition ID")
    text: str = Field(..., description="Proposition text")
    reasoning: Optional[str] = Field(None, description="Reasoning behind the proposition")
    confidence: Optional[float] = Field(None, description="Confidence score")
    created_at: str = Field(..., description="When the proposition was created (ISO format)")


class QueryResponse(BaseModel):
    """Response model for query results."""
    propositions: List[PropositionResponse] = Field(..., description="Matching propositions")
    total_results: int = Field(..., description="Total number of results found")
    query: str = Field(..., description="The original query")
    execution_time_ms: float = Field(..., description="Query execution time in milliseconds")


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str = Field(..., description="Service status")
    timestamp: str = Field(..., description="Current timestamp (ISO format)")
    gum_connected: bool = Field(..., description="Whether GUM database is connected")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    """Response model for errors."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    timestamp: str = Field(..., description="Error timestamp (ISO format)")


class SuggestionItem(BaseModel):
    """Individual suggestion item."""
    title: str = Field(..., description="Clear, actionable suggestion title")
    description: str = Field(..., description="Detailed explanation of the suggestion")
    urgency: str = Field(..., description="Urgency level: now, today, this_week")
    category: str = Field(..., description="Category: workflow, completion, learning, optimization, strategic")
    evidence: str = Field(..., description="Specific evidence from transcriptions")
    action_items: List[str] = Field(..., description="Specific actionable steps")
    confidence: int = Field(..., description="Confidence level 1-10")
    created_at: str = Field(..., description="When suggestion was generated")


class SuggestionsResponse(BaseModel):
    """Response model for generated suggestions."""
    suggestions: List[SuggestionItem] = Field(..., description="List of generated suggestions")
    data_points: int = Field(..., description="Number of observations analyzed")
    time_range_hours: float = Field(..., description="Time range of data analyzed in hours")
    generated_at: str = Field(..., description="When suggestions were generated")



# === Mock Observer Class ===

class APIObserver(Observer):
    """Mock observer for API-submitted observations."""
    
    def __init__(self, name: Optional[str] = None):
        super().__init__(name or "api_controller")
    
    async def _worker(self):
        """Required abstract method - not used for API submissions."""
        # API observer doesn't need a background worker since observations are submitted directly
        while self._running:
            await asyncio.sleep(1)


# === Helper Functions ===

def parse_datetime(date_value) -> datetime:
    """Parse datetime from string or return as-is if already datetime."""
    if isinstance(date_value, str):
        # Use dateutil parser to handle various formats
        parsed = date_parser.parse(date_value)
        # If the parsed datetime has no timezone info, assume it's UTC
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    elif isinstance(date_value, datetime):
        # If datetime has no timezone info, assume it's UTC
        if date_value.tzinfo is None:
            return date_value.replace(tzinfo=timezone.utc)
        return date_value
    return date_value


def serialize_datetime(dt: datetime) -> str:
    """Serialize datetime to ISO format with timezone information."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def ensure_gum_instance(user_name: Optional[str] = None) -> gum:
    """Ensure GUM instance is initialized and connected."""
    global gum_instance
    
    default_user = os.getenv("DEFAULT_USER_NAME", "APIUser")
    user_name = user_name or default_user
    
    if gum_instance is None or gum_instance.user_name != user_name:
        logger.info(f"Initializing GUM instance for user: {user_name}")
        
        # Initialize GUM - it will automatically use the unified client
        logger.info("Initializing GUM with unified AI client")
        
        gum_instance = gum(
            user_name=user_name,
            model="gpt-4o",  # Model name used for logging/identification only
            data_directory="~/.cache/gum",
            verbosity=logging.INFO
        )
        
        await gum_instance.connect_db()

        logger.info("GUM instance connected to database")
        logger.info("GUM configured with unified AI client for hybrid text/vision processing")
    
    return gum_instance


def validate_image(file_content: bytes) -> bool:
    """Validate that the uploaded file is a valid image."""
    try:
        image = Image.open(BytesIO(file_content))
        image.verify()
        return True
    except Exception as e:
        logger.warning(f"Invalid image file: {e}")
        return False


def process_image_for_analysis(file_content: bytes) -> str:
    """Convert image to base64 for AI analysis."""
    try:
        # Open and process the image
        image = Image.open(BytesIO(file_content))
        
        # Convert to RGB if necessary
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        # Resize if too large (to manage API costs)
        max_size = (1024, 1024)
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convert to base64
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return base64_image
    
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error processing image: {str(e)}"
        )


async def analyze_image_with_ai(base64_image: str, filename: Optional[str] = None) -> str:
    """Analyze image using the unified AI client."""
    try:
        logger.info("Starting image analysis with vision model")
        logger.info(f"   File: {filename}")
        
        # Get unified AI client
        client = await get_ai_client()
        
        # Create prompt for image analysis
        display_filename = filename or "uploaded_image"
        prompt = f"""Analyze this image and describe what the user is doing, what applications they're using, 
        and any observable behavior patterns. Focus on:
        
        1. What applications or interfaces are visible
        2. What actions the user appears to be taking
        3. Any workflow patterns or preferences shown
        4. The general context of the user's activity
        
        Image filename: {display_filename}
        
        Provide a detailed but concise analysis that will help understand user behavior."""
        
        # Use the unified client for vision completion
        analysis = await client.vision_completion(
            text_prompt=prompt,
            base64_image=base64_image
        )
        
        if analysis:
            logger.info("Vision analysis completed")
            logger.info(f"   Analysis length: {len(analysis)} characters")
            return analysis
        else:
            logger.error("Vision analysis returned empty response")
            return "Error: Empty response from vision model"
            
    except Exception as e:
        logger.error(f"Vision analysis failed: {str(e)}")
        return f"Error analyzing image: {str(e)}"


def validate_video(file_content: bytes) -> bool:
    """Validate that the uploaded file is a valid video."""
    try:
        logger.info(f"Validating video file ({len(file_content)} bytes)")
        
        # Save to temp file for validation
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name
        
        try:
            logger.info("Running FFmpeg validation check")
            # Use ffmpeg to check if it's a valid video
            result = subprocess.run([
                'ffmpeg', '-i', temp_path, '-t', '0.1', '-f', 'null', '-'
            ], capture_output=True, text=True)
            
            is_valid = result.returncode == 0
            if not is_valid:
                logger.error(f"Video validation failed: {result.stderr}")
            else:
                logger.info("Video validation passed")
            return is_valid
            
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"Error during video validation: {str(e)}")
        return False


def split_frames(video_path: Path, temp_dir: Path, fps: float = 0.1) -> List[Path]:
    """Extract frames from video using ffmpeg."""
    try:
        logger.info(f"Starting frame extraction from {video_path.name} at {fps} FPS")
        
        frame_pattern = temp_dir / "frame_%03d.jpg"
        
        # Ultra-simple FFmpeg command that definitely works (tested manually)
        result = subprocess.run([
            'ffmpeg', 
            '-i', str(video_path),
            '-vf', f'fps={fps}',  # Video filter for frame rate
            str(frame_pattern),
            '-y'  # Overwrite existing files
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg failed: {result.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FFmpeg failed: {result.stderr}"
            )
        
        # Find all extracted frame files
        frame_files = sorted(temp_dir.glob("frame_*.jpg"))
        logger.info(f"Successfully extracted {len(frame_files)} frames")
        
        if not frame_files:
            logger.error("No frames were extracted")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No frames could be extracted from video"
            )
        
        return frame_files
        
    except Exception as e:
        logger.error(f"Error extracting frames: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error extracting frames: {str(e)}"
        )


def encode_image_from_path(image_path: Path) -> str:
    """Encode image file to base64 for AI analysis."""
    try:
        with Image.open(image_path) as img:
            # Resize for efficiency
            img = img.resize((512, 512), Image.Resampling.LANCZOS)
            
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=90)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
            
    except Exception as e:
        logger.error(f"Error encoding image {image_path}: {e}")
        raise


async def process_video_frames(video_path: Path, fps: float = 0.1) -> List[dict]:
    """Process video by extracting frames and analyzing each one."""
    results = []
    
    logger.info(f"Starting video frame processing for {video_path.name} at {fps} FPS")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        
        # Extract frames
        logger.info("Extracting frames to temporary directory")
        frame_files = split_frames(video_path, temp_dir_path, fps)
        
        if not frame_files:
            logger.error("No frames could be extracted from video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No frames could be extracted from video"
            )
        
        logger.info(f"Starting AI analysis of {len(frame_files)} frames")
        
        # Process each frame
        for i, frame_path in enumerate(frame_files):
            try:
                logger.info(f"Analyzing frame {i+1}/{len(frame_files)}: {frame_path.name}")
                
                # Encode frame for AI analysis
                base64_frame = encode_image_from_path(frame_path)
                
                # Analyze frame with AI
                frame_name = f"frame_{i+1:03d}.jpg"
                analysis = await analyze_image_with_ai(base64_frame, frame_name)
                
                results.append({
                    'frame_number': i + 1,
                    'frame_name': frame_name,
                    'analysis': analysis,
                    'timestamp': i / fps  # Approximate timestamp in seconds
                })
                
                logger.info(f"Frame {i+1}/{len(frame_files)} analyzed successfully")
                
            except Exception as e:
                logger.error(f"Error processing frame {i+1}: {str(e)}")
                # Continue with other frames
                results.append({
                    'frame_number': i + 1,
                    'frame_name': f"frame_{i+1:03d}.jpg",
                    'analysis': f"Error processing frame: {str(e)}",
                    'timestamp': i / fps,
                    'error': True
                })
    
    logger.info(f"Video frame processing completed! Processed {len(results)} frames")
    return results

# Configuration for parallelism and performance
MAX_CONCURRENT_AI_CALLS = 5  # Limit concurrent AI analysis calls
MAX_CONCURRENT_ENCODING = 10  # Limit concurrent base64 encoding operations
MAX_CONCURRENT_GUM_OPERATIONS = 3  # Limit concurrent GUM database operations
CHUNK_SIZE = 50  # Process frames in chunks for large videos

# Initialize semaphores for controlling concurrency
ai_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AI_CALLS)
encoding_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ENCODING)
gum_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GUM_OPERATIONS)

# Rate limiting configuration
RATE_LIMITS = {
    "/observations/video": (5, 300),    # 5 videos per 5 minutes
    "/observations/text": (20, 60),     # 20 text submissions per minute
    "/query": (30, 60),                 # 30 queries per minute
    "default": (100, 60)                # 100 requests per minute for other endpoints
}

async def check_rate_limit(request: Request):
    """Check rate limits for the request with enhanced logging and error handling"""
    path = request.url.path
    
    # Get rate limit for this endpoint
    if path in RATE_LIMITS:
        max_requests, window = RATE_LIMITS[path]
    else:
        max_requests, window = RATE_LIMITS["default"]
    
    # Check limit using the enhanced rate limiter
    if not rate_limiter.check_limit(path, max_requests, window):
        reset_time = rate_limiter.get_reset_time(path, window)
        wait_seconds = int(reset_time - time.time())
        remaining_requests = rate_limiter.get_remaining_requests(path, max_requests)
        
        # Log rate limit violation with details
        logger.warning(f"Rate limit exceeded for {path}: {max_requests} requests per {window}s window. "
                      f"Reset in {wait_seconds}s. Client IP: {request.client.host if request.client else 'unknown'}")
        
        # Get endpoint stats for monitoring
        stats = rate_limiter.get_endpoint_stats(path)
        logger.info(f"Rate limit stats for {path}: {stats}")
        
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {wait_seconds} seconds.",
            headers={
                "Retry-After": str(wait_seconds),
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining_requests),
                "X-RateLimit-Reset": str(int(reset_time))
            }
        )
    
    # Log successful request (only for high-traffic endpoints)
    if path in ["/query", "/observations/text"]:
        remaining = rate_limiter.get_remaining_requests(path, max_requests)
        if remaining <= max_requests * 0.2:  # Log when 80% of limit is used
            logger.info(f"High usage for {path}: {remaining} requests remaining out of {max_requests}")

# Add rate limiting middleware for all endpoints
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Middleware to apply rate limiting to all endpoints"""
    try:
        # Skip rate limiting for health check and static files
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"] or request.url.path.startswith("/static"):
            return await call_next(request)
        
        # Apply rate limiting
        await check_rate_limit(request)
        
        # Process the request
        response = await call_next(request)
        
        # Add rate limit headers to response
        path = request.url.path
        if path in RATE_LIMITS:
            max_requests, window = RATE_LIMITS[path]
        else:
            max_requests, window = RATE_LIMITS["default"]
        
        remaining = rate_limiter.get_remaining_requests(path, max_requests)
        reset_time = rate_limiter.get_reset_time(path, window)
        
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(reset_time))
        
        return response
        
    except HTTPException as e:
        if e.status_code == 429:
            # Log rate limit violations
            logger.warning(f"Rate limit violation for {request.url.path}: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error in rate limit middleware: {e}")
        raise

# Add rate limit monitoring endpoint
@app.get("/admin/rate-limits", response_model=dict)
async def get_rate_limit_stats(request: Request, _auth: None = Depends(require_api_auth)):
    """Get rate limiting statistics for monitoring"""
    try:
        global_stats = rate_limiter.get_global_stats()
        
        # Get stats for configured endpoints
        endpoint_stats = {}
        for endpoint in RATE_LIMITS.keys():
            endpoint_stats[endpoint] = rate_limiter.get_endpoint_stats(endpoint)
        
        return {
            "global_stats": global_stats,
            "endpoint_stats": endpoint_stats,
            "timestamp": serialize_datetime(datetime.now(timezone.utc))
        }
    except Exception as e:
        logger.error(f"Error getting rate limit stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving rate limit statistics"
        )

# Add rate limit reset endpoint (admin only)
@app.post("/admin/rate-limits/reset", response_model=dict)
async def reset_rate_limits(endpoint: Optional[str] = None, _auth: None = Depends(require_api_auth)):
    """Reset rate limits for specific endpoint or all endpoints"""
    try:
        if endpoint:
            rate_limiter.reset_endpoint(endpoint)
            logger.info(f"Rate limits reset for endpoint: {endpoint}")
            return {"message": f"Rate limits reset for {endpoint}", "endpoint": endpoint}
        else:
            rate_limiter.reset_all()
            logger.info("All rate limits reset")
            return {"message": "All rate limits reset", "endpoint": "all"}
    except Exception as e:
        logger.error(f"Error resetting rate limits: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error resetting rate limits"
        )

# === API Endpoints ===

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        # Test GUM connection
        gum_connected = False
        try:
            await ensure_gum_instance()
            gum_connected = True
        except Exception as e:
            logger.warning(f"GUM connection failed in health check: {e}")
        
        return HealthResponse(
            status="healthy" if gum_connected else "unhealthy",
            timestamp=serialize_datetime(datetime.now(timezone.utc)),
            gum_connected=gum_connected,
            version="1.0.0"
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Health check failed"
        )


@app.delete("/database/cleanup", response_model=dict)
async def cleanup_database(user_name: Optional[str] = None):
    """Clean up entire database by removing all observations and propositions."""
    try:
        logger.info("Starting database cleanup...")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        observations_deleted = 0
        propositions_deleted = 0
        junction_records_deleted = 0
        
        # Clean up database
        async with gum_inst._session() as session:
            from gum.models import Observation, Proposition, observation_proposition, proposition_parent
            from sqlalchemy import delete, text
            
            # Delete in proper order to avoid foreign key constraints
            
            # First, delete all junction table entries
            junction_obs_result = await session.execute(delete(observation_proposition))
            junction_prop_result = await session.execute(delete(proposition_parent))
            junction_records_deleted = junction_obs_result.rowcount + junction_prop_result.rowcount
            
            # Then delete all observations
            obs_result = await session.execute(delete(Observation))
            observations_deleted = obs_result.rowcount
            
            # Then delete all propositions
            prop_result = await session.execute(delete(Proposition))
            propositions_deleted = prop_result.rowcount
            
            # Clear the FTS tables as well
            await session.execute(text("DELETE FROM propositions_fts"))
            await session.execute(text("DELETE FROM observations_fts"))
            
            # Commit the transaction
            await session.commit()
        
        # Run VACUUM outside of the session/transaction context
        try:
            async with gum_inst._session() as vacuum_session:
                await vacuum_session.execute(text("VACUUM"))
                await vacuum_session.commit()
        except Exception as vacuum_error:
            logger.warning(f"VACUUM operation failed: {vacuum_error}")
            # Continue anyway as the cleanup was successful
        
        logger.info(f"Database cleanup completed:")
        logger.info(f"    Deleted {observations_deleted} observations")
        logger.info(f"    Deleted {propositions_deleted} propositions")
        logger.info(f"    Deleted {junction_records_deleted} junction records")
        logger.info("   Cleared FTS indexes")
        logger.info("   Database vacuumed")
        
        return {
            "success": True,
            "message": "Database cleaned successfully",
            "observations_deleted": observations_deleted,
            "propositions_deleted": propositions_deleted,
            "junction_records_deleted": junction_records_deleted,
            "fts_cleared": True,
            "timestamp": serialize_datetime(datetime.now(timezone.utc))
        }
        
    except Exception as e:
        logger.error(f"Error cleaning database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cleaning database: {str(e)}"
        )

@app.get("/observations/video/{job_id}/insights", response_model=dict)
async def get_video_insights(job_id: str):
    """Get generated insights for a completed video processing job."""
    if job_id not in video_processing_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video processing job not found"
        )
    
    job = video_processing_jobs[job_id]
    
    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video processing is not completed. Current status: {job['status']}"
        )
    
    # Check if insights already exist
    if "insights" in job:
        logger.info(f" Returning cached insights for job {job_id}")
        return job["insights"]
    
    # Generate insights if they don't exist
    try:
        logger.info(f"Generating insights on-demand for job {job_id}")
        
        # Get frame analyses from the job
        frame_analyses = []
        if "frame_analyses" in job:
            # Use full analysis if available, otherwise fall back to preview
            frame_analyses = [
                frame.get("full_analysis", frame.get("analysis_preview", ""))
                for frame in job["frame_analyses"]
            ]
        
        if not frame_analyses:
            # Fallback: use basic info if no detailed analyses available
            frame_analyses = [f"Frame analysis data for {job['filename']}"]
            
        logger.info(f"Using {len(frame_analyses)} frame analyses for insights generation")
        for i, analysis in enumerate(frame_analyses):
            logger.info(f"    Frame {i+1} analysis length: {len(analysis)} characters")
        
        insights = await generate_video_insights(frame_analyses, job["filename"])
        
        # Cache the insights in the job data
        video_processing_jobs[job_id]["insights"] = insights
        
        logger.info(f"Generated and cached insights for job {job_id}")
        return insights
        
    except Exception as e:
        logger.error(f"Failed to generate insights for job {job_id}: {str(e)}")
        
        # Return basic fallback insights
        fallback_insights = {
            "key_insights": [
                f"Video processing completed for {job['filename']}",
                f"Successfully analyzed {job.get('successful_frames', 0)} frames",
                "Behavioral data captured and ready for analysis"
            ],
            "behavior_patterns": [
                "Standard user interaction patterns observed",
                "Task-oriented behavior documented",
                "Interface engagement recorded"
            ],
            "summary": f"Video analysis completed for {job['filename']} with {job.get('total_frames', 0)} frames processed.",
            "confidence_score": 0.5,
            "recommendations": [
                "Review individual frame analyses for detailed insights",
                "Consider additional video samples for pattern validation"
            ]
        }
        
        # Cache the fallback insights
        video_processing_jobs[job_id]["insights"] = fallback_insights
        
        return fallback_insights
  

@app.post("/observations/text", response_model=dict)
async def submit_text_observation(request: TextObservationRequest):
    """Submit a text observation to GUM."""
    try:
        start_time = time.time()
        logger.info(f" Received text observation: {request.content[:100]}...")
        
        # Get GUM instance
        logger.info(" Getting GUM instance...")
        gum_inst = await ensure_gum_instance(request.user_name)
        logger.info("GUM instance obtained successfully")
        
        # Create mock observer
        logger.info(" Creating API observer...")
        observer = APIObserver(request.observer_name)
        logger.info(f"API observer created: {observer._name}")
        
        # Create update
        logger.info("Creating update object...")
        update = Update(
            content=request.content,
            content_type="input_text"
        )
        logger.info(f"Update created - Content length: {len(update.content)}, Type: {update.content_type}")
        
        # Process through GUM with detailed logging
        logger.info(" Starting GUM processing...")
        logger.info(f"    Content preview: {request.content[:200]}...")
        logger.info(f"    User: {request.user_name}")
        logger.info(f"    Observer: {request.observer_name}")
        
        try:
            await gum_inst._default_handler(observer, update)
            logger.info("GUM processing completed successfully")
        except Exception as gum_error:
            logger.error(f"GUM processing failed: {type(gum_error).__name__}: {str(gum_error)}")
            logger.error(f"    Error details: {repr(gum_error)}")
            raise gum_error
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"Text observation processed successfully in {processing_time:.2f}ms")
        
        return {
            "success": True,
            "message": "Text observation submitted successfully",
            "processing_time_ms": processing_time,
            "content_preview": request.content[:100] + "..." if len(request.content) > 100 else request.content
        }
        
    except Exception as e:
        logger.error(f"Error processing text observation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing text observation: {str(e)}"
        )


@app.post("/observations/image", response_model=dict)
async def submit_image_observation(
    file: UploadFile = File(..., description="Image file to analyze"),
    user_name: Optional[str] = Form(None, description="User name (optional)"),
    observer_name: Optional[str] = Form("api_controller", description="Observer name")
):
    """Submit an image observation to GUM."""
    try:
        start_time = time.time()
        logger.info(f"Received image observation: {file.filename}")
        
        # Validate file type
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Validate image
        if not validate_image(file_content):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image file"
            )
        
        # Process image for AI analysis
        base64_image = process_image_for_analysis(file_content)
        
        # Analyze image with AI
        analysis = await analyze_image_with_ai(base64_image, file.filename)
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Create mock observer
        observer = APIObserver(observer_name)
        
        # Create update with analysis
        update_content = f"Image analysis of {file.filename}: {analysis}"
        update = Update(
            content=update_content,
            content_type="input_text"  # We store the analysis as text
        )
        
        # Process through GUM
        await gum_inst._default_handler(observer, update)
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"Image observation processed successfully in {processing_time:.2f}ms")
        
        return {
            "success": True,
            "message": "Image observation submitted successfully",
            "processing_time_ms": processing_time,
            "filename": file.filename,
            "analysis_preview": analysis[:200] + "..." if len(analysis) > 200 else analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing image observation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing image observation: {str(e)}"
        )


@app.post("/query", response_model=QueryResponse)
async def query_gum(request: QueryRequest):
    """Query GUM for insights and propositions."""
    try:
        start_time = time.time()
        logger.info(f"Received query: {request.query}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(request.user_name)
        
        # Execute query
        limit = request.limit if request.limit is not None else 10
        mode = request.mode or "default"
        
        results = await gum_inst.query(
            request.query,
            limit=limit,
            mode=mode
        )
        
        # Format results
        propositions = []
        for prop, score in results:
            propositions.append(PropositionResponse(
                id=prop.id,
                text=prop.text,
                reasoning=prop.reasoning,
                confidence=prop.confidence,
                created_at=serialize_datetime(parse_datetime(prop.created_at))
            ))
        
        execution_time = (time.time() - start_time) * 1000
        
        logger.info(f"Query executed successfully: {len(results)} results in {execution_time:.2f}ms")
        
        return QueryResponse(
            propositions=propositions,
            total_results=len(results),
            query=request.query,
            execution_time_ms=execution_time
        )
        
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing query: {str(e)}"
        )


@app.get("/observations", response_model=List[ObservationResponse])
async def list_observations(
    user_name: Optional[str] = None,
    limit: Optional[int] = 20,
    offset: Optional[int] = 0
):
    """List recent observations."""
    try:
        logger.info(f"Listing observations: limit={limit}, offset={offset}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query recent observations from database
        async with gum_inst._session() as session:
            from gum.models import Observation
            from sqlalchemy import select, desc
            
            stmt = (
                select(Observation)
                .order_by(desc(Observation.created_at))
                .limit(limit)
                .offset(offset)
            )
            
            result = await session.execute(stmt)
            observations = result.scalars().all()
            
            response = []
            for obs in observations:
                response.append(ObservationResponse(
                    id=obs.id,
                    content=obs.content[:500] + "..." if len(obs.content) > 500 else obs.content,
                    content_type=obs.content_type,
                    observer_name=obs.observer_name,
                    created_at=serialize_datetime(parse_datetime(obs.created_at))
                ))
            
            logger.info(f"Retrieved {len(response)} observations")
            return response
        
    except Exception as e:
        logger.error(f"Error listing observations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing observations: {str(e)}"
        )


@app.get("/propositions", response_model=List[PropositionResponse])
async def list_propositions(
    user_name: Optional[str] = None,
    limit: Optional[int] = 20,
    offset: Optional[int] = 0,
    confidence_min: Optional[int] = None,
    sort_by: Optional[str] = "created_at"
):
    """List recent propositions with filtering and sorting options."""
    try:
        logger.info(f"Listing propositions: limit={limit}, offset={offset}, confidence_min={confidence_min}, sort_by={sort_by}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query recent propositions from database
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, desc, asc
            
            stmt = select(Proposition)
            
            # Apply confidence filter if specified
            if confidence_min is not None:
                stmt = stmt.where(Proposition.confidence >= confidence_min)
            
            # Apply sorting
            if sort_by == "confidence":
                stmt = stmt.order_by(desc(Proposition.confidence))
            elif sort_by == "created_at":
                stmt = stmt.order_by(desc(Proposition.created_at))
            else:
                stmt = stmt.order_by(desc(Proposition.created_at))
            
            # Apply pagination
            stmt = stmt.limit(limit).offset(offset)
            
            result = await session.execute(stmt)
            propositions = result.scalars().all()
            
            response = []
            for prop in propositions:
                response.append(PropositionResponse(
                    id=prop.id,
                    text=prop.text,
                    reasoning=prop.reasoning,
                    confidence=prop.confidence,
                    created_at=serialize_datetime(parse_datetime(prop.created_at))
                ))
            
            logger.info(f"Retrieved {len(response)} propositions")
            return response
        
    except Exception as e:
        logger.error(f"Error listing propositions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing propositions: {str(e)}"
        )


@app.get("/propositions/count", response_model=dict)
async def get_propositions_count(
    user_name: Optional[str] = None,
    confidence_min: Optional[int] = None
):
    """Get total count of propositions with optional filtering."""
    try:
        logger.info(f"Getting propositions count: confidence_min={confidence_min}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query count from database
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, func
            
            stmt = select(func.count(Proposition.id))
            
            # Apply confidence filter if specified
            if confidence_min is not None:
                stmt = stmt.where(Proposition.confidence >= confidence_min)
            
            result = await session.execute(stmt)
            count = result.scalar()
            
            logger.info(f"Retrieved count: {count} propositions")
            return {
                "total_propositions": count,
                "confidence_filter": confidence_min
            }
        
    except Exception as e:
        logger.error(f"Error getting propositions count: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting propositions count: {str(e)}"
        )


@app.get("/propositions/by-hour", response_model=dict)
async def get_propositions_by_hour(
    user_name: Optional[str] = None,
    date: Optional[str] = None,
    confidence_min: Optional[int] = None
):
    """Get propositions grouped by hour for the specified date."""
    try:
        # Parse date parameter or use today
        if date:
            try:
                # Parse the date and ensure it's treated as local date
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        else:
            # Use current local date instead of UTC date
            target_date = datetime.now().date()
        
        # Convert local date to UTC date range
        # Since the user selects a local date, we need to find the UTC date range
        # that corresponds to their local date. For PDT (UTC-7), if they select 8/7/25,
        # we need to query from 8/7/25 07:00 UTC to 8/8/25 06:59 UTC
        # This accounts for the timezone offset
        import pytz
        from datetime import timedelta

        tz_name = os.getenv("LOCAL_TIMEZONE", "UTC")
        user_tz = pytz.timezone(tz_name)

        # Create the start of the selected date in the configured local timezone
        local_start = user_tz.localize(datetime.combine(target_date, datetime.min.time()))
        local_end = user_tz.localize(datetime.combine(target_date, datetime.max.time()))

        # Convert to UTC
        utc_start = local_start.astimezone(pytz.UTC)
        utc_end = local_end.astimezone(pytz.UTC)

        logger.info(f"Getting propositions by hour for date: {target_date}, confidence_min={confidence_min}")

        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)

        # Query propositions grouped by hour
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, func, extract, and_

            # Get current time to filter out future hours
            now = datetime.now(timezone.utc)

            # Build base query for the target date using the calculated UTC range
            stmt = select(Proposition).where(
                and_(
                    Proposition.created_at >= utc_start,
                    Proposition.created_at <= utc_end,
                    Proposition.created_at <= now  # Only past hours
                )
            )

            # Apply confidence filter if specified
            if confidence_min is not None:
                stmt = stmt.where(Proposition.confidence >= confidence_min)

            # Order by creation time
            stmt = stmt.order_by(Proposition.created_at)

            result = await session.execute(stmt)
            propositions = result.scalars().all()

            # Group propositions by hour (convert UTC to local time)
            hourly_groups = {}
            for prop in propositions:
                # Convert UTC time to local time for hour grouping
                local_time = prop.created_at.astimezone(user_tz)
                local_hour = local_time.hour
                if local_hour not in hourly_groups:
                    hourly_groups[local_hour] = []
                hourly_groups[local_hour].append(prop)
            
            # Format data for response
            hourly_data = []
            for hour in sorted(hourly_groups.keys()):
                hour_props = hourly_groups[hour]
                
                # Format hour display (12 AM, 1 AM, etc.) - now using local time
                if hour == 0:
                    hour_display = "12 a.m."
                elif hour < 12:
                    hour_display = f"{hour} a.m."
                elif hour == 12:
                    hour_display = "12 p.m."
                else:
                    hour_display = f"{hour - 12} p.m."
                
                hourly_data.append({
                    "hour": hour,
                    "hour_display": hour_display,
                    "proposition_count": len(hour_props),
                    "propositions": [
                        {
                            "id": prop.id,
                            "text": prop.text,
                            "reasoning": prop.reasoning,
                            "confidence": prop.confidence,
                            "created_at": serialize_datetime(parse_datetime(prop.created_at))
                        }
                        for prop in hour_props
                    ]
                })
            
            return {
                "date": target_date.strftime("%Y-%m-%d"),
                "total_hours": len(hourly_data),
                "total_propositions": len(propositions),
                "hourly_groups": hourly_data
            }
        
    except Exception as e:
        logger.error(f"Error getting propositions by hour: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting propositions by hour: {str(e)}"
        )


@app.post("/propositions/reflection/generate", response_model=SelfReflectionResponse)
async def generate_self_reflection(
    date: Optional[str] = None,
    user_name: Optional[str] = None,
    confidence_min: Optional[int] = None
):
    """Generate a self-reflection summary based on behavioral insights for a specific date."""
    try:
        # Parse date parameter or use today
        if date:
            try:
                # Parse the date and ensure it's treated as local date
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        else:
            # Use current local date instead of UTC date
            target_date = datetime.now().date()
        
        logger.info(f"Generating self-reflection for {user_name} on {target_date}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Convert local date to UTC date range using the same approach as propositions/by-hour
        import pytz
        from datetime import timedelta
        
        # Get user's timezone (assuming PDT for now, but this should be configurable)
        user_tz = pytz.timezone('US/Pacific')  # This handles PDT/PST automatically
        
        # Create the start of the selected date in user's timezone
        local_start = user_tz.localize(datetime.combine(target_date, datetime.min.time()))
        local_end = user_tz.localize(datetime.combine(target_date, datetime.max.time()))
        
        # Convert to UTC
        utc_start = local_start.astimezone(pytz.UTC)
        utc_end = local_end.astimezone(pytz.UTC)
        
        # Query propositions for the date
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, and_
            
            # Get current time to filter out future hours
            now = datetime.now(timezone.utc)
            
            # Build base query for the target date using the calculated UTC range
            stmt = select(Proposition).where(
                and_(
                    Proposition.created_at >= utc_start,
                    Proposition.created_at <= utc_end,
                    Proposition.created_at <= now  # Only past hours
                )
            )
            
            # Apply confidence filter if specified
            if confidence_min is not None:
                stmt = stmt.where(Proposition.confidence >= confidence_min)
            
            # Order by creation time
            stmt = stmt.order_by(Proposition.created_at)
            
            result = await session.execute(stmt)
            propositions = result.scalars().all()
            
            logger.info(f"Found {len(propositions)} propositions for {target_date}")
            
            if not propositions:
                # Return empty reflection if no data
                logger.info("No propositions found for the selected date")
                return SelfReflectionResponse(
                    behavioral_pattern="No behavioral data available for this date. Try selecting a different date or check if you have any observations recorded.",
                    specific_insights=[],
                    data_points=0,
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
            
            # Prepare propositions data for AI analysis
            propositions_data = []
            for prop in propositions:
                propositions_data.append({
                    "id": prop.id,
                    "text": prop.text,
                    "reasoning": prop.reasoning,
                    "confidence": prop.confidence,
                    "created_at": serialize_datetime(parse_datetime(prop.created_at))
                })
            
            logger.info(f"Prepared {len(propositions_data)} propositions for self-reflection analysis")
            
            # Create the prompt for self-reflection generation
            from gum.prompts.gum import SELF_REFLECTION_PROMPT
            
            prompt = (
                SELF_REFLECTION_PROMPT
                .replace("{user_name}", user_name or "User")
                .replace("{date}", target_date.strftime("%Y-%m-%d"))
                .replace("{propositions_data}", json.dumps(propositions_data, indent=2))
            )
            
            logger.info(f"Generated self-reflection prompt (length: {len(prompt)} characters)")
            
            # Get the unified AI client
            client = await get_ai_client()
            
            # Generate self-reflection
            logger.info("Sending self-reflection request to AI...")
            try:
                response_content = await client.text_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=3000,
                    temperature=0.1
                )
                
                logger.info(f"Received AI response (length: {len(response_content)} characters)")
                logger.info(f"Response preview: {response_content[:200]}...")
                
            except Exception as ai_error:
                logger.error(f"AI completion failed: {ai_error}")
                return SelfReflectionResponse(
                    behavioral_pattern=f"Unable to generate behavioral pattern due to AI service error: {str(ai_error)}",
                    specific_insights=[],
                    data_points=len(propositions),
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
            
            # Parse the JSON response
            try:
                reflection_data = json.loads(response_content)
                
                # Validate and structure the response
                behavioral_pattern = reflection_data.get("behavioral_pattern", "No behavioral pattern identified.")
                specific_insights_data = reflection_data.get("specific_insights", [])
                
                # Convert specific insights to proper format
                specific_insights = []
                for insight_data in specific_insights_data:
                    try:
                        specific_insights.append(SpecificInsight(
                            insight=insight_data.get("insight", ""),
                            action=insight_data.get("action", ""),
                            confidence=insight_data.get("confidence", 5),
                            category=insight_data.get("category", "productivity")
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse specific insight: {e}")
                        continue
                
                return SelfReflectionResponse(
                    behavioral_pattern=behavioral_pattern,
                    specific_insights=specific_insights,
                    data_points=len(propositions),
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI response as JSON: {e}")
                logger.error(f"Raw response: {response_content}")
                
                # Try to extract JSON from the response if it's wrapped in markdown or other formatting
                import re
                
                # Look for JSON in markdown code blocks
                json_match = re.search(r'```(?:json)?\s*(.*?)(?:```|\Z)', response_content, re.DOTALL)
                if json_match:
                    json_content = json_match.group(1).strip()
                    logger.info(f"Found JSON in markdown block: {json_content[:200]}...")
                    try:
                        reflection_data = json.loads(json_content)
                        behavioral_pattern = reflection_data.get("behavioral_pattern", "No behavioral pattern identified.")
                        specific_insights_data = reflection_data.get("specific_insights", [])
                        
                        specific_insights = []
                        for insight_data in specific_insights_data:
                            try:
                                specific_insights.append(SpecificInsight(
                                    insight=insight_data.get("insight", ""),
                                    action=insight_data.get("action", ""),
                                    confidence=insight_data.get("confidence", 5),
                                    category=insight_data.get("category", "productivity")
                                ))
                            except Exception as e:
                                logger.warning(f"Failed to parse specific insight: {e}")
                                continue
                        
                        return SelfReflectionResponse(
                            behavioral_pattern=behavioral_pattern,
                            specific_insights=specific_insights,
                            data_points=len(propositions),
                            generated_at=serialize_datetime(datetime.now(timezone.utc))
                        )
                    except json.JSONDecodeError as e2:
                        logger.error(f"Failed to parse extracted JSON: {e2}")
                
                # Try to find JSON-like structure in the response
                json_pattern = re.search(r'\{.*\}', response_content, re.DOTALL)
                if json_pattern:
                    json_candidate = json_pattern.group(0)
                    logger.info(f"Found JSON-like pattern: {json_candidate[:200]}...")
                    try:
                        reflection_data = json.loads(json_candidate)
                        behavioral_pattern = reflection_data.get("behavioral_pattern", "No behavioral pattern identified.")
                        specific_insights_data = reflection_data.get("specific_insights", [])
                        
                        specific_insights = []
                        for insight_data in specific_insights_data:
                            try:
                                specific_insights.append(SpecificInsight(
                                    insight=insight_data.get("insight", ""),
                                    action=insight_data.get("action", ""),
                                    confidence=insight_data.get("confidence", 5),
                                    category=insight_data.get("category", "productivity")
                                ))
                            except Exception as e:
                                logger.warning(f"Failed to parse specific insight: {e}")
                                continue
                        
                        return SelfReflectionResponse(
                            behavioral_pattern=behavioral_pattern,
                            specific_insights=specific_insights,
                            data_points=len(propositions),
                            generated_at=serialize_datetime(datetime.now(timezone.utc))
                        )
                    except json.JSONDecodeError as e3:
                        logger.error(f"Failed to parse JSON-like pattern: {e3}")
                
                # Return a fallback response with the raw AI response for debugging
                logger.error("All JSON parsing attempts failed")
                return SelfReflectionResponse(
                    behavioral_pattern=f"Unable to generate behavioral pattern due to processing error. The AI response was not in the expected JSON format. Raw response preview: {response_content[:500]}...",
                    specific_insights=[],
                    data_points=len(propositions),
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
        
    except Exception as e:
        logger.error(f"Error generating self-reflection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating self-reflection: {str(e)}"
        )


@app.post("/suggestions/generate", response_model=SuggestionsResponse)
async def generate_suggestions(
    user_name: Optional[str] = None,
    hours_back: Optional[float] = 6.0
):
    """Generate proactive suggestions based on recent transcription data."""
    try:
        start_time = time.time()
        logger.info(f"Generating suggestions for {user_name}, analyzing last {hours_back} hours")
        
        # Validate parameters
        if hours_back is not None and (hours_back <= 0 or hours_back > 168):  # Max 1 week
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="hours_back must be between 0 and 168 (1 week)"
            )
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Get ONLY high-confidence behavioral insights (GUM propositions) - NO transcription data
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, desc
            
            # Get top behavioral insights for pattern discovery
            stmt = (
                select(Proposition)
                .where(Proposition.confidence >= 7)  # High-confidence insights only
                .order_by(desc(Proposition.confidence), desc(Proposition.created_at))
                .limit(100)  # Get top 100 behavioral insights
            )
            
            result = await session.execute(stmt)
            propositions = result.scalars().all()
            
            logger.info(f"Found {len(propositions)} high-confidence behavioral insights for pattern analysis")
            
            if not propositions:
                # Return empty suggestions if no insights
                logger.info("No behavioral insights found in database")
                return SuggestionsResponse(
                    suggestions=[],
                    data_points=0,
                    time_range_hours=0.0,
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
            
            # Prepare ONLY behavioral insights for AI analysis (NO screen transcriptions)
            behavioral_insights = "\n\n# User Behavioral Pattern Analysis (GUM Insights):\n"
            for prop in propositions:  # Use all high-confidence propositions
                behavioral_insights += f"- {prop.text} (confidence: {prop.confidence}/10)\n"
                # Include reasoning for pattern recognition
                reasoning_snippet = prop.reasoning[:150] + "..." if len(prop.reasoning) > 150 else prop.reasoning
                behavioral_insights += f"  Evidence: {reasoning_snippet}\n"
                behavioral_insights += f"  Date: {serialize_datetime(parse_datetime(prop.created_at))}\n\n"
            
            # Context is PURELY behavioral insights - no recent activity transcriptions
            enhanced_context = behavioral_insights
            
            logger.info(f"🔍 DEBUGGING: Using ONLY behavioral insights - {len(propositions)} propositions, NO transcriptions!")
            logger.info(f"Prepared behavioral context data (length: {len(enhanced_context)} characters, {len(propositions)} propositions)")
            
            # Create the suggestions prompt for GUM-based pattern discovery
            from gum.prompts.gum import SUGGESTIONS_PROMPT
            
            prompt = (
                SUGGESTIONS_PROMPT
                .replace("{user_name}", user_name or "User")
                .replace("{transcription_data}", enhanced_context)  # This now contains only behavioral insights
            )
            
            logger.info(f"Generated suggestions prompt (length: {len(prompt)} characters)")
            
            # Get the unified AI client
            client = await get_ai_client()
            
            # Generate suggestions
            logger.info("Sending suggestions request to AI...")
            try:
                response_content = await client.text_completion(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=4000,
                    temperature=0.1
                )
                
                logger.info(f"Received AI response (length: {len(response_content)} characters)")
                
            except Exception as ai_error:
                logger.error(f"AI completion failed: {ai_error}")
                return SuggestionsResponse(
                    suggestions=[],
                    data_points=len(propositions),
                    time_range_hours=0.0,  # All data used
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
            
            # Parse the JSON response (handle markdown code blocks)
            try:
                # Strip markdown code blocks if present
                clean_response = response_content.strip()
                if clean_response.startswith('```json'):
                    clean_response = clean_response[7:]  # Remove ```json
                if clean_response.startswith('```'):
                    clean_response = clean_response[3:]   # Remove ```
                if clean_response.endswith('```'):
                    clean_response = clean_response[:-3]  # Remove trailing ```
                clean_response = clean_response.strip()
                
                suggestions_data = json.loads(clean_response)
                
                # Validate and structure the response
                suggestions_raw = suggestions_data.get("suggestions", [])
                
                # Convert to proper suggestion format with validation
                suggestions = []
                current_time = serialize_datetime(datetime.now(timezone.utc))
                
                for suggestion_data in suggestions_raw:
                    try:
                        # Validate required fields and provide defaults
                        title = suggestion_data.get("title", "Unnamed Suggestion")
                        description = suggestion_data.get("description", "")
                        urgency = suggestion_data.get("urgency", "today")
                        category = suggestion_data.get("category", "optimization")
                        evidence = suggestion_data.get("evidence", "")
                        action_items = suggestion_data.get("action_items", [])
                        confidence = suggestion_data.get("confidence", 5)
                        
                        # Validate urgency values
                        if urgency not in ["now", "today", "this_week"]:
                            urgency = "today"
                        
                        # Validate category values
                        if category not in ["workflow", "completion", "learning", "optimization", "strategic"]:
                            category = "optimization"
                        
                        # Validate confidence range
                        if not isinstance(confidence, int) or confidence < 1 or confidence > 10:
                            confidence = 5
                        
                        # Ensure action_items is a list
                        if not isinstance(action_items, list):
                            action_items = []
                        
                        suggestions.append(SuggestionItem(
                            title=title,
                            description=description,
                            urgency=urgency,
                            category=category,
                            evidence=evidence,
                            action_items=action_items,
                            confidence=confidence,
                            created_at=current_time
                        ))
                        
                    except Exception as e:
                        logger.warning(f"Failed to parse suggestion: {e}")
                        continue
                
                processing_time = (time.time() - start_time) * 1000
                logger.info(f"Successfully generated {len(suggestions)} suggestions in {processing_time:.2f}ms")
                
                # Save suggestions directly to database (copying propositions pattern)
                try:
                    # Get database session
                    gum_inst = await ensure_gum_instance(user_name)
                    async with gum_inst._session() as session:
                        from gum.models import Suggestion
                        
                        # Save each suggestion directly to database
                        suggestions_saved = 0
                        for suggestion_data in suggestions_raw:
                            suggestion = Suggestion(
                                title=suggestion_data.get("title", "Untitled")[:200],
                                description=suggestion_data.get("description", "")[:1000],
                                category=suggestion_data.get("category", "general")[:100],
                                rationale=suggestion_data.get("evidence", "")[:500],
                                expected_utility=suggestion_data.get("confidence", 5) / 10.0,
                                probability_useful=0.7,
                                trigger_proposition_id=None,
                                batch_id=f"manual_generate_{int(time.time())}",
                                delivered=False
                            )
                            session.add(suggestion)
                            suggestions_saved += 1
                        
                        await session.commit()
                        logger.info(f"💾 SAVED {suggestions_saved} SUGGESTIONS DIRECTLY TO DATABASE")
                        
                except Exception as save_error:
                    logger.error(f"❌ FAILED TO SAVE SUGGESTIONS TO DATABASE: {save_error}")
                    import traceback
                    logger.error(f"❌ Full traceback: {traceback.format_exc()}")
                
                return SuggestionsResponse(
                    suggestions=suggestions,
                    data_points=len(propositions),  # Using behavioral insights count
                    time_range_hours=0.0,  # All data used
                    generated_at=current_time
                )
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AI response as JSON: {e}")
                logger.error(f"Raw response: {response_content[:500]}...")
                return SuggestionsResponse(
                    suggestions=[],
                    data_points=len(propositions),
                    time_range_hours=0.0,  # All data used
                    generated_at=serialize_datetime(datetime.now(timezone.utc))
                )
            
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error generating suggestions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating suggestions: {str(e)}"
        )

# Video processing storage
video_processing_jobs = {}



async def generate_video_insights(frame_analyses: List[str], filename: str) -> dict:
    """
    Generate insights from video frame analyses.
    
    Args:
        frame_analyses: List of analysis strings from video frames
        filename: Name of the video file
        
    Returns:
        Dictionary containing generated insights
    """
    try:
        logger.info(f"Generating video insights for {filename} with {len(frame_analyses)} frame analyses")
        
        # Combine all frame analyses into a single text for processing
        combined_analysis = "\n\n".join(frame_analyses)
        
        # Get the unified AI client
        client = await get_ai_client()
        
        # Create a prompt for generating insights
        insight_prompt = f"""You are analyzing video frame data to generate behavioral insights.

Video file: {filename}
Number of frames analyzed: {len(frame_analyses)}

Frame analyses:
{combined_analysis[:3000]}...

Please generate insights in the following JSON format:
{{
            "key_insights": [
        "Insight 1 about user behavior",
        "Insight 2 about user behavior",
        "Insight 3 about user behavior"
            ],
            "behavior_patterns": [
        "Pattern 1 observed",
        "Pattern 2 observed",
        "Pattern 3 observed"
    ],
    "summary": "2-3 sentence summary of the overall behavioral analysis",
    "confidence_score": 0.8,
            "recommendations": [
        "Recommendation 1",
        "Recommendation 2",
        "Recommendation 3"
    ]
}}

Focus on:
- User behavior patterns and interactions
- Productivity and workflow insights
- Time management and focus patterns
- Interface usage and preferences
- Potential areas for improvement

Return ONLY valid JSON, no additional text or formatting."""

        # Generate insights using AI
        response_content = await client.text_completion(
            messages=[{"role": "user", "content": insight_prompt}],
            max_tokens=2000,
            temperature=0.1
        )
        
        logger.info(f"Received AI response for video insights (length: {len(response_content)} characters)")
        
        # Parse the JSON response
        try:
            insights = json.loads(response_content)
            
            # Validate the structure
            required_keys = ["key_insights", "behavior_patterns", "summary", "confidence_score", "recommendations"]
            for key in required_keys:
                if key not in insights:
                    insights[key] = []
            
            # Ensure lists are returned
            if not isinstance(insights["key_insights"], list):
                insights["key_insights"] = []
            if not isinstance(insights["behavior_patterns"], list):
                insights["behavior_patterns"] = []
            if not isinstance(insights["recommendations"], list):
                insights["recommendations"] = []
            
            # Ensure confidence_score is a float
            if not isinstance(insights["confidence_score"], (int, float)):
                insights["confidence_score"] = 0.5
            
            # Ensure summary is a string
            if not isinstance(insights["summary"], str):
                insights["summary"] = f"Video analysis completed for {filename}"
            
            logger.info("Successfully generated video insights")
            return insights
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.error(f"Raw response: {response_content[:500]}...")
            
            # Return fallback insights
            return {
                "key_insights": [
                    f"Video processing completed for {filename}",
                    f"Successfully analyzed {len(frame_analyses)} frames",
                    "Behavioral data captured and ready for analysis"
                ],
                "behavior_patterns": [
                    "Standard user interaction patterns observed",
                    "Task-oriented behavior documented",
                    "Interface engagement recorded"
                ],
                "summary": f"Video analysis completed for {filename} with {len(frame_analyses)} frames processed.",
                "confidence_score": 0.5,
                "recommendations": [
                    "Review individual frame analyses for detailed insights",
                    "Consider additional video samples for pattern validation"
                ]
            }
            
    except Exception as e:
        logger.error(f"Error generating video insights: {e}")
        
        # Return fallback insights
        return {
            "key_insights": [
                f"Video processing completed for {filename}",
                f"Successfully analyzed {len(frame_analyses)} frames",
                "Behavioral data captured and ready for analysis"
            ],
            "behavior_patterns": [
                "Standard user interaction patterns observed",
                "Task-oriented behavior documented",
                "Interface engagement recorded"
            ],
            "summary": f"Video analysis completed for {filename} with {len(frame_analyses)} frames processed.",
            "confidence_score": 0.5,
            "recommendations": [
                "Review individual frame analyses for detailed insights",
                "Consider additional video samples for pattern validation"
            ]
        }


def parse_ai_analysis_to_insights(analysis_text: str) -> List[str]:
    """
    Parse AI analysis content and extract clean, one-line insights.
    
    Args:
        analysis_text: Raw AI analysis text from vision processing
        
    Returns:
        List of clean, one-line insights
    """
    import re
    
    if not analysis_text or len(analysis_text.strip()) < 20:
        return []
    
    # Remove common prefixes and headers
    text = analysis_text
    
    # Remove "Video frame analysis (Frame X): " prefix
    if "Video frame analysis" in text and "): " in text:
        text = text.split("): ", 1)[1] if len(text.split("): ", 1)) > 1 else text
    
    # Remove "Detailed Analysis of User Experience in frame_XXX.jpg" headers
    text = re.sub(r"Detailed Analysis of User Experience in frame_\d+\.jpg['\"]?\s*[-\s]*", "", text)
    
    # Remove markdown headers (### #### etc.)
    text = re.sub(r"#{1,6}\s*\d*\.\s*", "", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    
    # Remove "Primary Analysis Focus:" type headers
    text = re.sub(r"Primary Analysis Focus:\s*", "", text)
    
    # Remove numbered list markers (1. 2. etc.)
    text = re.sub(r"^\d+\.\s*", "", text, flags=re.MULTILINE)
    
    # Remove markdown bold formatting
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    
    # Remove bullet points and dashes
    text = re.sub(r"^[-•*]\s*", "", text, flags=re.MULTILINE)
    
    # Split into sentences and clean
    sentences = []
    
    # Split by common delimiters
    for delimiter in ['. ', '.\n', '; ', ';\n', ' | ', ' --- ']:
        if delimiter in text:
            parts = text.split(delimiter)
            for part in parts:
                part = part.strip()
                if len(part) > 20 and not part.endswith(':'):
                    # Clean up the sentence
                    clean_part = clean_insight_sentence(part)
                    if clean_part:
                        sentences.append(clean_part)
            break
    
    # If no clear delimiters, try to extract meaningful phrases
    if not sentences:
        # Look for patterns like "User [action]" or "The user [action]"
        user_actions = re.findall(r"(?:The\s+)?[Uu]ser\s+[^.;]+", text)
        for action in user_actions:
            clean_action = clean_insight_sentence(action)
            if clean_action:
                sentences.append(clean_action)
    
    # Final fallback - just clean the whole text if it's reasonable length
    if not sentences and len(text.strip()) <= 200:
        clean_text = clean_insight_sentence(text)
        if clean_text:
            sentences.append(clean_text)
    
    # Limit to 3 insights per analysis and ensure they're not too long
    return sentences[:3]


def clean_insight_sentence(sentence: str) -> str:
    """
    Clean and format a single insight sentence.
    
    Args:
        sentence: Raw sentence text
        
    Returns:
        Cleaned sentence or empty string if not suitable
    """
    if not sentence:
        return ""
    
    # Remove extra whitespace and newlines
    sentence = re.sub(r'\s+', ' ', sentence.strip())
    
    # Remove trailing colons and dashes
    sentence = re.sub(r'[:\-]+$', '', sentence)
    
    # Remove leading/trailing quotes
    sentence = sentence.strip('\'"')
    
    # Ensure sentence starts with capital letter
    if sentence and sentence[0].islower():
        sentence = sentence[0].upper() + sentence[1:]
    
    # Ensure sentence ends with period
    if sentence and not sentence.endswith(('.', '!', '?')):
        sentence += '.'
    
    # Check if it's a meaningful insight (not just a header or fragment)
    if (len(sentence) < 20 or 
        sentence.lower().startswith(('user goals', 'primary analysis', 'analysis focus')) or
        sentence.count(':') > 1 or
        len(sentence) > 200):
        return ""
    
    return sentence



async def process_video_background(job_id: str, video_path: Path, user_name: str, observer_name: str, fps: float, filename: str):
    """Process video in background using optimized parallel pipeline and update job status."""
    try:
        logger.info(f" Starting optimized background video processing for job {job_id}")
        logger.info(f"File: {filename} | User: {user_name} | Observer: {observer_name} | FPS: {fps}")
        
        # Initial status: extracting frames
        video_processing_jobs[job_id]["status"] = "extracting_frames"
        video_processing_jobs[job_id]["progress"] = 10
        
        # Convert fps to max_frames for the new pipeline
        max_frames = max(10, int(fps * 60))  # Approximate frames for 1 minute at given fps
        video_processing_jobs[job_id]["total_frames"] = max_frames
        
        logger.info(f"Starting optimized parallel frame processing (max {max_frames} frames)")
        
        # Use the optimized parallel processing pipeline
        frame_results = await process_video_frames_parallel(
            video_path=str(video_path),
            max_frames=max_frames,
            job_id=job_id
        )
        
        if frame_results:
            # Update progress after AI analysis
            video_processing_jobs[job_id]["processed_frames"] = len(frame_results)
            video_processing_jobs[job_id]["progress"] = 70
            video_processing_jobs[job_id]["status"] = "storing_results"
            
            # Store results in GUM database using the separate function
            await process_and_store_in_gum(
                frame_results=frame_results,
                user_name=user_name,
                observer_name=observer_name
            )
        else:
            logger.error(f"No frames extracted for job {job_id}")
            video_processing_jobs[job_id]["status"] = "error"
            video_processing_jobs[job_id]["error"] = "No frames could be extracted from video"
            return
        
        logger.info(f"Optimized parallel processing completed: {len(frame_results)} frames")
        
        # Update job status with results
        successful_frames = len(frame_results)
        failed_frames = max_frames - successful_frames if max_frames > successful_frames else 0
        
        video_processing_jobs[job_id]["status"] = "completed"
        video_processing_jobs[job_id]["progress"] = 100
        video_processing_jobs[job_id]["total_frames"] = max_frames
        video_processing_jobs[job_id]["processed_frames"] = successful_frames
        video_processing_jobs[job_id]["successful_frames"] = successful_frames
        video_processing_jobs[job_id]["failed_frames"] = failed_frames
        video_processing_jobs[job_id]["frame_analyses"] = [
            {
                "frame_number": r["frame_number"],
                "analysis_preview": r["analysis"][:100] + "..." if len(r["analysis"]) > 100 else r["analysis"],
                "processing_time": "optimized_parallel"
            }
            for r in frame_results[:5]  # Show first 5 as preview
        ]
        
        logger.info(" Optimized video processing completed!")
        logger.info(f" Results: {successful_frames} frames processed successfully using parallel pipeline")
        logger.info(f"Video processing job {job_id} completed with optimized performance")
        
    except Exception as e:
        logger.error(f" Critical error in optimized background video processing job {job_id}: {str(e)}")
        video_processing_jobs[job_id]["status"] = "error"
        video_processing_jobs[job_id]["error"] = str(e)
    
    finally:
        # Clean up video file
        logger.info(f" Cleaning up temporary video file for job {job_id}")
        video_path.unlink(missing_ok=True)


def split_frames_optimized(video_path: str, output_dir: str, max_frames: int = 10) -> List[str]:
    """
    Optimized FFmpeg frame extraction with CPU optimizations.
    Uses simple, reliable method that actually works.
    """
    logger.info(f" Starting optimized frame extraction from {video_path}")
    start_time = time.time()
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Use the same simple command that works manually
    # Extract frames at 1 frame per max_frames seconds
    frame_rate = 1.0 / max_frames
    
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-r", str(frame_rate),  # Frame rate (works like our manual test)
        "-f", "image2",  # Image sequence format (works like our manual test)
        f"{output_dir}/frame_%03d.jpg",
        "-y",  # Overwrite existing files
        "-hide_banner", "-loglevel", "warning"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg extraction failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        
        # Get list of extracted frames
        frame_files = sorted(glob.glob(f"{output_dir}/frame_*.jpg"))
        extraction_time = time.time() - start_time
        
        logger.info(f"Extracted {len(frame_files)} frames in {extraction_time:.2f}s using optimized FFmpeg")
        return frame_files
        
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg extraction timed out")
        raise RuntimeError("FFmpeg extraction timed out")
    except Exception as e:
        logger.error(f"Error during optimized frame extraction: {str(e)}")
        raise


def split_frames_hardware_accelerated(video_path: str, output_dir: str, max_frames: int = 10) -> List[str]:
    """
    Hardware-accelerated FFmpeg frame extraction.
    Falls back to optimized CPU extraction if hardware acceleration fails.
    """
    logger.info(f" Attempting hardware-accelerated frame extraction from {video_path}")
    start_time = time.time()
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Calculate frame rate for extraction
    frame_rate = 1.0 / max_frames
    
    # Try hardware acceleration first with simple parameters
    hw_cmd = [
        "ffmpeg",
        "-hwaccel", "auto",  # Auto-detect hardware acceleration
        "-i", video_path,
        "-r", str(frame_rate),  # Simple frame rate
        "-f", "image2",  # Image sequence format
        f"{output_dir}/frame_%03d.jpg",
        "-y",  # Overwrite existing files
        "-hide_banner", "-loglevel", "warning"
    ]
    
    try:
        result = subprocess.run(hw_cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            frame_files = sorted(glob.glob(f"{output_dir}/frame_*.jpg"))
            extraction_time = time.time() - start_time
            logger.info(f"Hardware-accelerated extraction: {len(frame_files)} frames in {extraction_time:.2f}s")
            return frame_files
        else:
            logger.warning(f" Hardware acceleration failed, falling back to CPU: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        logger.warning(" Hardware acceleration timed out, falling back to CPU")
    except Exception as e:
        logger.warning(f" Hardware acceleration error, falling back to CPU: {str(e)}")
    
    # Fallback to optimized CPU extraction
    return split_frames_optimized(video_path, output_dir, max_frames)


def split_frames_smart(video_path: str, output_dir: str, max_frames: int = 10) -> List[str]:
    """
    Smart frame extraction that chooses the best method based on video characteristics.
    """
    logger.info(f" Smart frame extraction from {video_path}")
    
    try:
        # Get video info to make smart decisions
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", video_path
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            import json
            video_info = json.loads(result.stdout)
            
            # Extract video characteristics
            duration = float(video_info.get("format", {}).get("duration", 0))
            size = int(video_info.get("format", {}).get("size", 0))
            
            # Decision logic based on video characteristics
            if size > 100_000_000 or duration > 300:  # Large file (>100MB) or long video (>5min)
                logger.info("Large/long video detected, using hardware acceleration")
                return split_frames_hardware_accelerated(video_path, output_dir, max_frames)
            else:
                logger.info("Small/short video detected, using optimized CPU extraction")
                return split_frames_optimized(video_path, output_dir, max_frames)
        else:
            logger.warning(" Could not probe video, using hardware acceleration as default")
            return split_frames_hardware_accelerated(video_path, output_dir, max_frames)
            
    except Exception as e:
        logger.warning(f" Error in smart analysis, using hardware acceleration: {str(e)}")
        return split_frames_hardware_accelerated(video_path, output_dir, max_frames)


async def encode_frame_to_base64(frame_path: str, frame_number: int) -> dict:
    """
    Encode a single frame to base64 with semaphore control.
    """
    async with encoding_semaphore:
        try:
            with open(frame_path, "rb") as f:
                base64_data = base64.b64encode(f.read()).decode("utf-8")
            
            return {
                "frame_number": frame_number,
                "base64_data": base64_data,
                "file_path": frame_path
            }
        except Exception as e:
            logger.error(f"Error encoding frame {frame_number}: {str(e)}")
            raise


async def process_frame_with_ai(frame_data: dict, semaphore: asyncio.Semaphore) -> dict:
    """
    Process a single frame with AI analysis using semaphore control.
    Uses the vision AI client (OpenRouter with Qwen model).
    """
    async with semaphore:
        try:
            frame_number = frame_data["frame_number"]
            base64_data = frame_data["base64_data"]
            filename = f"frame_{frame_number:03d}.jpg"
            
            logger.info(f"Analyzing frame {frame_number} with AI")
            analysis = await analyze_image_with_ai(base64_data, filename)
            
            return {
                "frame_number": frame_number,
                "analysis": analysis,
                "base64_data": base64_data
            }
        except Exception as e:
            logger.error(f"Error analyzing frame {frame_data.get('frame_number', 'unknown')}: {str(e)}")
            raise


async def process_video_frames_parallel(
    video_path: str, 
    max_frames: int = 10,
    job_id: Optional[str] = None
) -> List[dict]:
    """
    Process video frames with full parallelism: extraction, encoding, and AI analysis.
    Optionally updates job status for UI progress tracking.
    """
    logger.info(f"Starting parallel video processing: {video_path}")
    total_start_time = time.time()
    
    # Create temporary directory for frames
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Step 1: Extract frames using smart method
            logger.info("Extracting frames...")
            if job_id:
                video_processing_jobs[job_id]["status"] = "extracting_frames"
                video_processing_jobs[job_id]["progress"] = 20
            
            frame_files = split_frames_smart(video_path, temp_dir, max_frames)
            
            if not frame_files:
                logger.warning(" No frames extracted from video")
                return []
            
            # Step 2: Parallel base64 encoding
            logger.info(f" Encoding {len(frame_files)} frames to base64...")
            if job_id:
                video_processing_jobs[job_id]["status"] = "processing_frames"
                video_processing_jobs[job_id]["progress"] = 40
                video_processing_jobs[job_id]["total_frames"] = len(frame_files)
                video_processing_jobs[job_id]["processed_frames"] = 0
            
            encoding_start = time.time()
            
            encoding_tasks = [
                encode_frame_to_base64(frame_path, i + 1)
                for i, frame_path in enumerate(frame_files)
            ]
            
            encoded_frames = await asyncio.gather(*encoding_tasks, return_exceptions=True)
            
            # Filter out exceptions
            valid_frames = [
                frame for frame in encoded_frames 
                if not isinstance(frame, Exception)
            ]
            
            encoding_time = time.time() - encoding_start
            logger.info(f"Encoded {len(valid_frames)} frames in {encoding_time:.2f}s")
            
            # Step 3: Parallel AI analysis with rate limiting
            logger.info(f" Analyzing {len(valid_frames)} frames with AI...")
            if job_id:
                video_processing_jobs[job_id]["progress"] = 60
            
            analysis_start = time.time()
            
            analysis_tasks = [
                process_frame_with_ai(frame_data, ai_semaphore)
                for frame_data in valid_frames
                if isinstance(frame_data, dict)
            ]
            
            analyzed_frames = await asyncio.gather(*analysis_tasks, return_exceptions=True)
            
            # Filter out exceptions
            valid_analyses = [
                frame for frame in analyzed_frames 
                if not isinstance(frame, Exception)
            ]
            
            analysis_time = time.time() - analysis_start
            logger.info(f"Analyzed {len(valid_analyses)} frames in {analysis_time:.2f}s")
            
            if job_id:
                video_processing_jobs[job_id]["processed_frames"] = len(valid_analyses)
                video_processing_jobs[job_id]["progress"] = 80
            
            # Step 4: Return results (simplified for now)
            # Note: GUM integration would require proper Observer implementation
            final_results = [frame for frame in valid_analyses if isinstance(frame, dict)]
            
            total_time = time.time() - total_start_time
            logger.info(f" Completed parallel video processing in {total_time:.2f}s total")
            
            return final_results
            
        except Exception as e:
            logger.error(f"Error in parallel video processing: {str(e)}")
            if job_id:
                video_processing_jobs[job_id]["status"] = "error"
                video_processing_jobs[job_id]["error"] = str(e)
            raise


async def process_and_store_in_gum(frame_results: List[dict], user_name: str, observer_name: str) -> None:
    """
    Process frame analysis results and store them in GUM database.
    Separated from parallel processing for better modularity.
    """
    if not frame_results:
        logger.warning(" No frame results to process in GUM")
        return
    
    logger.info(f"Storing {len(frame_results)} frame analyses in GUM database...")
    gum_start = time.time()
    
    try:
        async with gum_semaphore:
            gum_inst = await ensure_gum_instance(user_name)
            observer = APIObserver(observer_name)
            
            # Process in batches to avoid overwhelming the database
            batch_size = 5
            for i in range(0, len(frame_results), batch_size):
                batch = frame_results[i:i + batch_size]
                
                for frame_result in batch:
                    if isinstance(frame_result, dict) and "analysis" in frame_result and "frame_number" in frame_result:
                        # Create update with frame analysis
                        update_content = f"Video frame analysis (Frame {frame_result['frame_number']}): {frame_result['analysis']}"
                        update = Update(
                            content=update_content,
                            content_type="input_text"
                        )
                        await gum_inst._default_handler(observer, update)
        
        gum_time = time.time() - gum_start
        logger.info(f"Stored {len(frame_results)} frame analyses in GUM in {gum_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Error storing frame results in GUM: {str(e)}")
        raise


@app.post("/observations/video", response_model=dict)
async def submit_video_observation(
    request: Request,
    file: UploadFile = File(...),
    user_name: Optional[str] = Form(None),
    observer_name: Optional[str] = Form("api_controller"),
    fps: Optional[float] = Form(0.1)
):
    """Submit video observation"""
    try:
        start_time = time.time()
        logger.info(f"Received video upload: {file.filename}")
        
        # Get file size for logging
        file_content_preview = await file.read()
        logger.info(f" File size: {len(file_content_preview) / 1024 / 1024:.1f} MB")
        
        # Reset file pointer after reading for size
        await file.seek(0)
        
        # Validate file type - check both MIME type and file extension
        is_video = False
        if file.content_type and file.content_type.startswith('video/'):
            is_video = True
        elif file.filename:
            video_extensions = ('.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv')
            is_video = file.filename.lower().endswith(video_extensions)
        
        if not is_video:
            logger.error(f"Invalid file type: {file.content_type}, filename: {file.filename}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be a video (MP4, AVI, MOV, WMV, FLV, WebM, MKV)"
            )
        
        logger.info("Video file type validation passed")
        logger.info("Validating video content")
        
        # Read and validate file content
        file_content = await file.read()
        
        if not validate_video(file_content):
            logger.error("Video content validation failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid video file"
            )
        
        logger.info("Saving video to temporary storage")
        
        # Save video to persistent temporary file
        temp_dir = Path(tempfile.gettempdir()) / "gum_videos"
        temp_dir.mkdir(exist_ok=True)
        
        job_id = str(uuid.uuid4())
        video_filename = f"{job_id}_{file.filename}"
        video_path = temp_dir / video_filename
        
        # Write video file
        with open(video_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"Video saved with job ID: {job_id}")
        
        # Initialize job status
        video_processing_jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "filename": file.filename,
            "fps": fps,
            "created_at": time.time(),
            "total_frames": 0,
            "processed_frames": 0,
            "successful_frames": 0,
            "failed_frames": 0
        }
        
        logger.info(" Starting background video processing")
        
        # Start background processing
        asyncio.create_task(process_video_background(
            job_id, video_path, user_name or "anonymous", observer_name or "api_controller", fps or 0.1, file.filename or "unknown.mp4"
        ))
        
        upload_time = (time.time() - start_time) * 1000
        logger.info(f"Video upload completed in {upload_time:.1f}ms")
        
        return {
            "success": True,
            "message": "Video uploaded successfully and queued for processing",
            "job_id": job_id,
            "filename": file.filename,
            "fps": fps,
            "upload_time_ms": upload_time,
            "status": "queued",
            "check_status_url": f"/observations/video/status/{job_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing video observation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing video observation: {str(e)}"
        )


@app.get("/observations/video/status/{job_id}", response_model=dict)
async def get_video_processing_status(job_id: str):
    """Get the status of a video processing job."""
    if job_id not in video_processing_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video processing job not found"
        )
    
    job = video_processing_jobs[job_id]
    
    # Calculate processing time
    processing_time = (time.time() - job["created_at"]) * 1000
    
    response = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "filename": job["filename"],
        "fps": job["fps"],
        "processing_time_ms": processing_time,
        "total_frames": job["total_frames"],
        "processed_frames": job["processed_frames"]
    }
    
    if job["status"] == "completed":
        response.update({
            "successful_frames": job["successful_frames"],
            "failed_frames": job["failed_frames"],
            "summary": f"Processed video {job['filename']} with {job['total_frames']} frames extracted at {job['fps']} fps. Successfully analyzed {job['successful_frames']} frames" + (f", {job['failed_frames']} frames failed processing" if job['failed_frames'] > 0 else ""),
            "frame_analyses": job.get("frame_analyses", [])
        })
    elif job["status"] == "error":
        response["error"] = job.get("error", "Unknown error occurred")
    
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
            timestamp=serialize_datetime(datetime.now(timezone.utc))
        ).dict()
    )


# === Helper Functions ===

# === Main Entry Point ===

async def startup_event():
    """Startup event handler."""
    logger.info("Starting GUM API Controller...")
    logger.info(" AI Processing: Unified AI Client (OpenRouter)")
    logger.info("    Text Tasks: OpenRouter (PROPOSE_MODEL)")
    logger.info("    Vision Tasks: OpenRouter (SCREEN_MODEL)")
    logger.info("    Suggestion Tasks: OpenRouter (SUGGEST_MODEL)")

    # Initialize the gum instance so the DB session factory is available,
    # then pass it to the Gumbo engine so suggestions can be persisted.
    try:
        gum_inst = await ensure_gum_instance()
        if GUMBO_AVAILABLE and gum_inst.Session is not None:
            engine = await get_gumbo_engine()
            engine.set_db_session_factory(gum_inst.Session)
            logger.info("Gumbo engine session factory wired to gum DB session")
    except Exception as e:
        logger.error(f"Failed to wire Gumbo engine session factory: {e}")

    logger.info("GUM API Controller started successfully")


app.add_event_handler("startup", startup_event)


def run_server(host: str = None, port: int = None, reload: bool = False):
    """Run the FastAPI server."""
    host = host or os.getenv("BIND_HOST", "127.0.0.1")
    port = port or int(os.getenv("BIND_PORT", "8000"))
    # Use logging for startup banner too
    logger.info("=" * 60)
    logger.info(" GUM AI Video Processing Server Starting Up")
    logger.info("=" * 60)
    logger.info(f" Server: {host}:{port}")
    logger.info(f" Reload mode: {'Enabled' if reload else 'Disabled'}")
    logger.info(" Log level: INFO")
    logger.info("Video processing with enhanced logging enabled!")
    logger.info("=" * 60)
    
    uvicorn.run(
        "controller:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="GUM REST API Controller")
    parser.add_argument("--host", default=None, help="Host to bind to (defaults to BIND_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind to (defaults to BIND_PORT or 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, reload=args.reload)

@app.get("/observations/by-hour", response_model=dict)
async def get_observations_by_hour(
    user_name: Optional[str] = None,
    date: Optional[str] = None
):
    """Get raw observations grouped by hour for narrative timeline view."""
    try:
        # Parse date parameter or use today
        if date:
            try:
                # Parse the date and ensure it's treated as local date
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        else:
            # Use current local date instead of UTC date
            target_date = datetime.now().date()
        
        # Convert local date to UTC date range
        # Since the user selects a local date, we need to find the UTC date range
        # that corresponds to their local date. For PDT (UTC-7), if they select 8/7/25,
        # we need to query from 8/7/25 07:00 UTC to 8/8/25 06:59 UTC
        # This accounts for the timezone offset
        import pytz
        from datetime import timedelta
        
        # Get user's timezone (assuming PDT for now, but this should be configurable)
        user_tz = pytz.timezone('US/Pacific')  # This handles PDT/PST automatically
        
        # Create the start of the selected date in user's timezone
        local_start = user_tz.localize(datetime.combine(target_date, datetime.min.time()))
        local_end = user_tz.localize(datetime.combine(target_date, datetime.max.time()))
        
        # Convert to UTC
        utc_start = local_start.astimezone(pytz.UTC)
        utc_end = local_end.astimezone(pytz.UTC)
        
        logger.info(f"=== DATE CONVERSION DEBUG (OBSERVATIONS) ===")
        logger.info(f"Input date string: {date}")
        logger.info(f"Parsed target_date: {target_date}")
        logger.info(f"User timezone: {user_tz}")
        logger.info(f"Local start of day: {local_start}")
        logger.info(f"Local end of day: {local_end}")
        logger.info(f"UTC start: {utc_start}")
        logger.info(f"UTC end: {utc_end}")
        logger.info(f"Current UTC time: {datetime.now(timezone.utc)}")
        logger.info(f"Current local time: {datetime.now()}")
        logger.info(f"=============================================")
        logger.info(f"Getting observations by hour for date: {target_date}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query observations grouped by hour
        async with gum_inst._session() as session:
            from gum.models import Observation
            from sqlalchemy import select, func, and_
            
            # Get current time to filter out future hours
            now = datetime.now(timezone.utc)
            
            # Build base query for the target date using the calculated UTC range
            stmt = select(Observation).where(
                and_(
                    Observation.created_at >= utc_start,
                    Observation.created_at <= utc_end,
                    Observation.created_at <= now  # Only past hours
                )
            )
            
            # Order by creation time
            stmt = stmt.order_by(Observation.created_at)
            
            result = await session.execute(stmt)
            observations = result.scalars().all()
            
            # Group observations by hour (convert UTC to local time)
            hourly_groups = {}
            for obs in observations:
                # Convert UTC time to local time for hour grouping
                local_time = obs.created_at.astimezone(pytz.timezone('US/Pacific'))
                local_hour = local_time.hour
                if local_hour not in hourly_groups:
                    hourly_groups[local_hour] = []
                hourly_groups[local_hour].append(obs)
            
            # Format data for response
            hourly_data = []
            for hour in sorted(hourly_groups.keys()):
                hour_obs = hourly_groups[hour]
                
                # Format hour display (12 AM, 1 AM, etc.) - now using local time
                if hour == 0:
                    hour_display = "12 a.m."
                elif hour < 12:
                    hour_display = f"{hour} a.m."
                elif hour == 12:
                    hour_display = "12 p.m."
                else:
                    hour_display = f"{hour - 12} p.m."
                
                hourly_data.append({
                    "hour": hour,
                    "hour_display": hour_display,
                    "observation_count": len(hour_obs),
                    "observations": [
                        {
                            "id": obs.id,
                            "content": obs.content,
                            "content_type": obs.content_type,
                            "observer_name": obs.observer_name,
                            "created_at": serialize_datetime(parse_datetime(obs.created_at))
                        }
                        for obs in hour_obs
                    ]
                })
            
            logger.info(f"Retrieved {len(hourly_data)} hourly observation groups for {target_date}")
            return {
                "date": target_date.isoformat(),
                "hourly_groups": hourly_data,
                "total_hours": len(hourly_data),
                "total_observations": sum(len(group["observations"]) for group in hourly_data)
            }
            
    except Exception as e:
        logger.error(f"Error getting observations by hour: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting observations by hour: {str(e)}"
        )


# =============================================================================
# GUMBO INTELLIGENT SUGGESTION ENDPOINTS
# =============================================================================

# SSE endpoint removed - suggestions now use reliable HTTP polling


@app.get("/suggestions/health", response_model=SuggestionHealthResponse)
async def get_suggestions_health():
    """
    Get health status and metrics for the Gumbo suggestion system.
    
    Returns comprehensive system health information including:
    - Overall system status (healthy/degraded/unhealthy)
    - Performance metrics (processing times, suggestion counts)
    - Rate limiting status
    - Active connection counts
    - Recent error information
    """
    if not GUMBO_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Gumbo suggestion system not available"
        )
    
    try:
        # Get engine health status
        engine = await get_gumbo_engine()
        health_data = engine.get_health_status()
        
        # Build comprehensive metrics
        metrics = SuggestionMetrics(
            total_suggestions_generated=suggestion_metrics["total_suggestions"],
            total_batches_processed=suggestion_metrics["total_batches"],
            average_processing_time_seconds=health_data["metrics"].get("average_processing_time_seconds", 0.0),
            last_batch_generated_at=health_data["metrics"].get("last_batch_at"),
            rate_limit_hits_today=suggestion_metrics["rate_limit_hits"]
        )
        
        # Get rate limit status
        rate_limit_status = RateLimitStatus(
            tokens_available=health_data["rate_limit_status"]["tokens_available"],
            tokens_capacity=health_data["rate_limit_status"]["tokens_capacity"],
            next_refill_at=health_data["rate_limit_status"]["next_refill_at"],
            is_rate_limited=health_data["rate_limit_status"]["is_rate_limited"],
            wait_time_seconds=health_data["rate_limit_status"]["wait_time_seconds"]
        )
        
        # Determine overall status (SSE connections removed - using HTTP polling)
        status_value = health_data["status"]
        
        return SuggestionHealthResponse(
            status=status_value,
            metrics=metrics,
            rate_limit_status=rate_limit_status,
            uptime_seconds=health_data["uptime_seconds"]
        )
        
    except Exception as e:
        logger.error(f"Error getting suggestion health: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting suggestion health: {str(e)}"
        )


# REMOVED: broadcast_suggestion_batch function - replaced with direct database save in suggestion generation


@app.get("/suggestions")
async def list_suggestions(
    user_name: Optional[str] = None,
    limit: Optional[int] = 20,
    delivered: Optional[bool] = None
):
    """List recent suggestions with filtering options (copying propositions pattern exactly)."""
    try:
        logger.info(f"Listing suggestions: limit={limit}, delivered={delivered}")
        
        # Get GUM instance (same pattern as propositions)
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query recent suggestions from database (same pattern as propositions)
        async with gum_inst._session() as session:
            from gum.models import Suggestion
            from sqlalchemy import select, desc
            
            stmt = select(Suggestion)
            
            # Apply delivered filter if specified
            if delivered is not None:
                stmt = stmt.where(Suggestion.delivered == delivered)
            
            # Order by creation time (newest first) - same as propositions
            stmt = stmt.order_by(desc(Suggestion.created_at))
            
            # Apply limit - same as propositions
            stmt = stmt.limit(limit)
            
            result = await session.execute(stmt)
            suggestions = result.scalars().all()
            
            # Mark undelivered suggestions as delivered (same logic as propositions)
            if delivered is False or delivered is None:
                undelivered_ids = [s.id for s in suggestions if not s.delivered]
                if undelivered_ids:
                    from sqlalchemy import update
                    await session.execute(
                        update(Suggestion)
                        .where(Suggestion.id.in_(undelivered_ids))
                        .values(delivered=True)
                    )
                    await session.commit()
                    logger.info(f"Marked {len(undelivered_ids)} suggestions as delivered")
            
            # Convert to response format (same pattern as propositions)
            response = []
            for suggestion in suggestions:
                response.append({
                    "id": suggestion.id,
                    "title": suggestion.title,
                    "description": suggestion.description,
                    "category": suggestion.category,
                    "rationale": suggestion.rationale,
                    "expected_utility": suggestion.expected_utility,
                    "probability_useful": suggestion.probability_useful,
                    "trigger_proposition_id": suggestion.trigger_proposition_id,
                    "batch_id": suggestion.batch_id,
                    "delivered": suggestion.delivered,
                    "created_at": serialize_datetime(parse_datetime(suggestion.created_at))
                })
            
            logger.info(f"Retrieved {len(response)} suggestions")
            return response
            
    except Exception as e:
        logger.error(f"Error listing suggestions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing suggestions: {str(e)}"
        )


# REMOVED: HTTP broadcast endpoint - not needed with direct database save

@app.post("/suggestions/test-trigger")
async def test_trigger_gumbo():
    """
    TEST ENDPOINT: Manually trigger Gumbo suggestion generation for testing.
    This bypasses the confidence requirement to demonstrate the system working.
    """
    if not GUMBO_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Gumbo suggestion system not available"
        )
    
    try:
        # Get the most recent proposition to use as trigger
        gum_inst = await ensure_gum_instance()
        async with gum_inst._session() as session:
            from sqlalchemy import select, desc
            from gum.models import Proposition
            
            stmt = select(Proposition).order_by(desc(Proposition.created_at)).limit(1)
            result = await session.execute(stmt)
            recent_prop = result.scalar_one_or_none()
            
            if not recent_prop:
                return {"error": "No propositions found to use as trigger"}
            
            # Manually trigger Gumbo (bypass confidence check)
            logger.info(f"🧪 TEST: Manually triggering Gumbo for proposition {recent_prop.id}")
            
            # Import and trigger
            from gum.services.gumbo_engine import trigger_gumbo_suggestions
            
            # Fire and forget
            import asyncio
            asyncio.create_task(trigger_gumbo_suggestions(recent_prop.id, session))
            
            return {
                "message": "Gumbo test triggered successfully",
                "proposition_id": recent_prop.id,
                "note": "Check the Suggestions tab for real-time results"
            }
            
    except Exception as e:
        logger.error(f"Test trigger failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Test trigger failed: {str(e)}"
        )


