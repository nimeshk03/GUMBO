# models.py

from __future__ import annotations

import pathlib
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    text as sql_text,
)
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.sql import func

class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all database models.
    
    This class provides the foundation for all SQLAlchemy models in the application,
    including async support and declarative base functionality.
    """
    pass

observation_proposition = Table(
    "observation_proposition",
    Base.metadata,
    Column(
        "observation_id",
        Integer,
        ForeignKey("observations.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "proposition_id",
        Integer,
        ForeignKey("propositions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

proposition_parent = Table(
    "proposition_parent",
    Base.metadata,
    Column(
        "child_id",
        Integer,
        ForeignKey("propositions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "parent_id",
        Integer,
        ForeignKey("propositions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Observation(Base):
    """Represents an observation of user behavior.
    
    This model stores observations made by various observers about user behavior,
    including the content of the observation and metadata about when and how it was made.

    Attributes:
        id (int): Primary key for the observation.
        observer_name (str): Name of the observer that made this observation.
        content (str): The actual content of the observation.
        content_type (str): Type of content (e.g., 'text', 'image', etc.).
        created_at (datetime): When the observation was created.
        updated_at (datetime): When the observation was last updated.
        propositions (set[Proposition]): Set of propositions related to this observation.
    """
    __tablename__ = "observations"

    id:            Mapped[int]   = mapped_column(primary_key=True)
    observer_name: Mapped[str]   = mapped_column(String(100), nullable=False)
    content:       Mapped[str]   = mapped_column(Text,        nullable=False)
    content_type:  Mapped[str]   = mapped_column(String(50),  nullable=False)

    created_at:    Mapped[str]   = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at:    Mapped[str]   = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    propositions: Mapped[set["Proposition"]] = relationship(
        "Proposition",
        secondary=observation_proposition,
        back_populates="observations",
        collection_class=set,
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        """String representation of the observation.
        
        Returns:
            str: A string representation showing the observation ID and observer name.
        """
        return f"<Observation(id={self.id}, observer={self.observer_name})>"


class Proposition(Base):
    """Represents a proposition about user behavior.
    
    This model stores propositions generated from observations, including the proposition
    text, reasoning behind it, and metadata about its creation and relationships.

    Attributes:
        id (int): Primary key for the proposition.
        text (str): The actual proposition text.
        reasoning (str): The reasoning behind this proposition.
        confidence (Optional[int]): Confidence level in this proposition.
        decay (Optional[int]): Decay factor for this proposition.
        created_at (datetime): When the proposition was created.
        updated_at (datetime): When the proposition was last updated.
        revision_group (str): Group identifier for related proposition revisions.
        version (int): Version number of this proposition.
        parents (set[Proposition]): Set of parent propositions.
        observations (set[Observation]): Set of observations related to this proposition.
    """
    __tablename__ = "propositions"

    id:         Mapped[int]           = mapped_column(primary_key=True)
    text:       Mapped[str]           = mapped_column(Text, nullable=False)
    reasoning:  Mapped[str]           = mapped_column(Text, nullable=False)
    confidence: Mapped[Optional[int]]
    decay:      Mapped[Optional[int]]

    created_at: Mapped[str]           = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str]           = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    revision_group: Mapped[str]       = mapped_column(String(36), nullable=False, index=True)
    version:        Mapped[int]       = mapped_column(Integer, server_default="1", nullable=False)

    parents: Mapped[set["Proposition"]] = relationship(
        "Proposition",
        secondary=proposition_parent,
        primaryjoin=id == proposition_parent.c.child_id,
        secondaryjoin=id == proposition_parent.c.parent_id,
        backref="children",
        collection_class=set,
        lazy="selectin",
    )

    observations: Mapped[set[Observation]] = relationship(
        "Observation",
        secondary=observation_proposition,
        back_populates="propositions",
        collection_class=set,
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        """String representation of the proposition.
        
        Returns:
            str: A string representation showing the proposition ID and a preview of its text.
        """
        preview = (self.text[:27] + "…") if len(self.text) > 30 else self.text
        return f"<Proposition(id={self.id}, text={preview})>"


class Suggestion(Base):
    """Represents an intelligent suggestion generated by the Gumbo engine.
    
    This model stores suggestions created from high-confidence propositions,
    including the suggestion content, metadata, and delivery tracking.

    Attributes:
        id (int): Primary key for the suggestion.
        title (str): The suggestion title.
        description (str): Detailed suggestion description.
        category (str): Suggestion category (e.g., 'productivity', 'workflow').
        rationale (str): AI reasoning for this suggestion.
        expected_utility (Optional[float]): Expected utility score.
        probability_useful (float): Probability this suggestion is useful (0-1).
        trigger_proposition_id (Optional[int]): FK to the proposition that triggered generation.
        batch_id (str): Unique identifier for the suggestion batch.
        delivered (bool): Whether suggestion has been delivered to frontend.
        trigger_proposition_text (Optional[str]): Snapshot of trigger proposition text.
        trigger_proposition_confidence (Optional[int]): Snapshot of trigger proposition confidence.
        trigger_proposition_reasoning (Optional[str]): Snapshot of trigger proposition reasoning.
        processing_time_seconds (Optional[float]): Seconds taken to generate this batch.
        context_propositions_count (Optional[int]): Number of context propositions used.
        generation_model (Optional[str]): Model used for generation (SUGGEST_MODEL env var).
        created_at (datetime): When the suggestion was created.
        updated_at (datetime): When the suggestion was last updated.
    """
    __tablename__ = "suggestions"

    id:                    Mapped[int]           = mapped_column(primary_key=True)
    title:                 Mapped[str]           = mapped_column(String(200), nullable=False)
    description:           Mapped[str]           = mapped_column(Text, nullable=False)
    category:              Mapped[str]           = mapped_column(String(100), nullable=False)
    rationale:             Mapped[str]           = mapped_column(Text, nullable=False)
    expected_utility:      Mapped[Optional[float]]
    probability_useful:    Mapped[float]         = mapped_column(nullable=False, default=0.5)
    trigger_proposition_id: Mapped[Optional[int]] = mapped_column(ForeignKey("propositions.id", ondelete="SET NULL"))
    batch_id:              Mapped[str]           = mapped_column(String(36), nullable=False, index=True)
    delivered:             Mapped[bool]          = mapped_column(nullable=False, default=False, index=True)

    # Snapshot of the trigger proposition at generation time — stored inline so
    # the suggestion row is self-contained for data export and sharing.
    trigger_proposition_text:       Mapped[Optional[str]]   = mapped_column(Text,         nullable=True)
    trigger_proposition_confidence: Mapped[Optional[int]]   = mapped_column(Integer,      nullable=True)
    trigger_proposition_reasoning:  Mapped[Optional[str]]   = mapped_column(Text,         nullable=True)

    # Batch-level generation metadata.
    processing_time_seconds:    Mapped[Optional[float]] = mapped_column(Float,        nullable=True)
    context_propositions_count: Mapped[Optional[int]]   = mapped_column(Integer,      nullable=True)
    generation_model:           Mapped[Optional[str]]   = mapped_column(String(100),  nullable=True)

    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        """String representation of the suggestion.
        
        Returns:
            str: A string representation showing the suggestion ID and title.
        """
        return f"<Suggestion(id={self.id}, title='{self.title[:50]}...')>"


FTS_TOKENIZER = "porter ascii"

def create_fts_table(conn) -> None:
    """Create FTS5 virtual table and triggers for proposition search.
    
    This function creates a full-text search table for propositions and sets up
    triggers to maintain the search index as propositions are modified.

    Args:
        conn: SQLite database connection.
    """
    exists = conn.execute(
        sql_text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='propositions_fts'"
        )
    ).fetchone()
    if exists:
        return

    conn.execute(
        sql_text(
            f"""
            CREATE VIRTUAL TABLE propositions_fts
            USING fts5(
                text,
                reasoning,
                content='propositions',
                content_rowid='id',
                tokenize='{FTS_TOKENIZER}'
            );
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER propositions_ai
            AFTER INSERT ON propositions BEGIN
                INSERT INTO propositions_fts(rowid, text, reasoning)
                VALUES (new.id, new.text, new.reasoning);
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER propositions_ad
            AFTER DELETE ON propositions BEGIN
                INSERT INTO propositions_fts(propositions_fts, rowid, text, reasoning)
                VALUES('delete', old.id, old.text, old.reasoning);
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            CREATE TRIGGER propositions_au
            AFTER UPDATE ON propositions BEGIN
                INSERT INTO propositions_fts(propositions_fts, rowid, text, reasoning)
                VALUES('delete', old.id, old.text, old.reasoning);
                INSERT INTO propositions_fts(rowid, text, reasoning)
                VALUES(new.id, new.text, new.reasoning);
            END;
        """
        )
    )
    conn.execute(
        sql_text(
            """
            INSERT INTO propositions_fts(rowid, text, reasoning)
            SELECT id, text, reasoning FROM propositions;
        """
        )
    )

def create_observations_fts(conn) -> None:
    """Create FTS5 virtual table and triggers for observation search.
    
    This function creates a full-text search table for observations and sets up
    triggers to maintain the search index as observations are modified.

    Args:
        conn: SQLite database connection.
    """
    exists = conn.execute(sql_text(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='observations_fts'"
    )).fetchone()
    if exists:
        return                      # already present

    conn.execute(sql_text(f"""
        CREATE VIRTUAL TABLE observations_fts
        USING fts5(
            content,
            content='observations',
            content_rowid='id',
            tokenize='{FTS_TOKENIZER}'
        );
    """))
    conn.execute(sql_text("""
        CREATE TRIGGER observations_ai
        AFTER INSERT ON observations BEGIN
            INSERT INTO observations_fts(rowid, content)
            VALUES (new.id, new.content);
        END;
    """))
    conn.execute(sql_text("""
        CREATE TRIGGER observations_ad
        AFTER DELETE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
        END;
    """))
    conn.execute(sql_text("""
        CREATE TRIGGER observations_au
        AFTER UPDATE ON observations BEGIN
            INSERT INTO observations_fts(observations_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
            INSERT INTO observations_fts(rowid, content)
            VALUES (new.id, new.content);
        END;
    """))
    # back-fill the index
    conn.execute(sql_text("""
        INSERT INTO observations_fts(rowid, content)
        SELECT id, content FROM observations;
    """))


def _migrate_suggestions_table(conn) -> None:
    """Add metadata columns to an existing suggestions table.

    SQLite does not support ALTER TABLE ... ADD COLUMN IF NOT EXISTS, so each
    statement is attempted individually and the OperationalError raised for
    duplicate column names is silenced.  This is a no-op on a fresh database
    because create_all will have already created the table with all columns.
    """
    new_columns = [
        ("trigger_proposition_text",       "TEXT"),
        ("trigger_proposition_confidence", "INTEGER"),
        ("trigger_proposition_reasoning",  "TEXT"),
        ("processing_time_seconds",        "REAL"),
        ("context_propositions_count",     "INTEGER"),
        ("generation_model",               "VARCHAR(100)"),
    ]
    for column_name, column_type in new_columns:
        try:
            conn.execute(sql_text(
                f"ALTER TABLE suggestions ADD COLUMN {column_name} {column_type}"
            ))
        except Exception:
            # Column already exists — safe to ignore.
            pass


async def init_db(
    db_path: str = "gum.db",
    db_directory: Optional[str] = None,
):
    """Create the SQLite file, ORM tables & FTS5 index (first run only)."""
    if db_directory:
        path = pathlib.Path(db_directory).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        db_path = str(path / db_path)

    engine: AsyncEngine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        future=True,
        connect_args={
            "timeout": 30,
            "isolation_level": None,
        },
        poolclass=None,
    )

    async with engine.begin() as conn:
        await conn.execute(sql_text("PRAGMA journal_mode=WAL"))
        await conn.execute(sql_text("PRAGMA busy_timeout=30000"))

        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(create_fts_table)
        await conn.run_sync(create_observations_fts)
        await conn.run_sync(_migrate_suggestions_table)

    Session = async_sessionmaker(
        engine, 
        expire_on_commit=False,
        autoflush=False
    )
    return engine, Session
