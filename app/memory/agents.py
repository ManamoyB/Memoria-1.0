"""Independently reusable context, classification, writing and quality agents."""

import json
from typing import Any

from app.memory.contracts import Classification, Extraction, MemoryInput
from app.memory.repository import MemoryError
from app.schemas.agent import MemoriaAgentId


class ContextAgent:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def execute(self, content: Any, source_id: Any) -> Any:
        result = self.llm.structured(
            "Extract atomic facts with exact source quotes. "
            "Distinguish inference from explicit facts. "
            "Each source_id must be " + json.dumps(source_id) + ". Return no candidates when no "
            "grounded facts exist. Source data follows:\n" + json.dumps(content),
            Extraction,
        )
        for candidate in result.candidates:
            for source in candidate.sources:
                if source.source_id != source_id or source.quote not in content:
                    raise MemoryError(
                        "Extracted candidate has unsupported provenance", "UNGROUNDED_OUTPUT", 422
                    )
        return result.candidates


class ClassificationAgent:
    def __init__(self, llm: Any) -> None:
        self.llm = llm

    def execute(self, candidate: Any) -> Any:
        classification = self.llm.structured(
            "Classify this memory: episodic = event, semantic = fact, procedural = instructions, "
            "preference = stable choice, project = project-specific knowledge. "
            "Do not change its facts.\n" + candidate.model_dump_json(),
            Classification,
        )
        return MemoryInput.model_validate(candidate.model_dump() | classification.model_dump())


class QualityAgent:
    def execute(self, candidate: Any) -> Any:
        candidate = MemoryInput.model_validate(candidate)
        names = {e.name.casefold() for e in candidate.entities}
        for relation in candidate.relationships:
            if relation.subject.casefold() not in names or relation.object.casefold() not in names:
                raise MemoryError(
                    "Relationship references an undeclared entity", "INVALID_RELATIONSHIP", 422
                )
        warnings = []
        if candidate.inferred:
            warnings.append("Inferred claim requires human review")
        if not candidate.entities:
            warnings.append("No entities identified")
        if candidate.confidence < 0.3:
            warnings.append("Low confidence")
        return {"quality_score": max(0, 1 - 0.2 * len(warnings)), "warnings": warnings}


class WriterAgent:
    def __init__(self, repo: Any, quality: Any) -> None:
        self.repo, self.quality = repo, quality

    def execute(self, user: Any, candidate: Any) -> Any:
        self.quality.execute(candidate)
        return self.repo.create(user, candidate, MemoriaAgentId.KNOWLEDGE_WRITER.value)
