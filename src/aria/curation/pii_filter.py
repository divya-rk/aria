"""PII detection and redaction using Presidio."""

from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine, RecognizerResult
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

from aria.common import get_logger


logger = get_logger(__name__)


@dataclass
class PIIResult:
    """Result of PII detection and redaction."""

    original_text: str
    redacted_text: str
    pii_detected: bool
    pii_count: int
    pii_types: list[str]
    findings: list[dict]


class PIIFilter:
    """Detect and redact PII from text content."""

    # PII entity types to detect
    DEFAULT_ENTITIES = [
        "PERSON",
        "EMAIL_ADDRESS",
        "PHONE_NUMBER",
        "CREDIT_CARD",
        "US_SSN",
        "US_PASSPORT",
        "US_DRIVER_LICENSE",
        "IP_ADDRESS",
        "IBAN_CODE",
        "NRP",  # National Registration Number
        "LOCATION",
        "DATE_TIME",
        "US_BANK_NUMBER",
        "CRYPTO",
        "MEDICAL_LICENSE",
    ]

    def __init__(
        self,
        entities: list[str] | None = None,
        score_threshold: float = 0.7,
        redaction_char: str = "*",
    ) -> None:
        """
        Initialize PII filter.

        Args:
            entities: List of PII entity types to detect
            score_threshold: Minimum confidence score for detection
            redaction_char: Character to use for redaction
        """
        self.entities = entities or self.DEFAULT_ENTITIES
        self.score_threshold = score_threshold
        self.redaction_char = redaction_char

        self._analyzer = AnalyzerEngine()
        self._anonymizer = AnonymizerEngine()

        logger.info(
            "pii_filter_initialized",
            entities=len(self.entities),
            threshold=score_threshold,
        )

    def detect(self, text: str) -> list[RecognizerResult]:
        """
        Detect PII in text without redacting.

        Args:
            text: Text to analyze

        Returns:
            List of PII findings
        """
        results = self._analyzer.analyze(
            text=text,
            entities=self.entities,
            language="en",
        )

        # Filter by score threshold
        return [r for r in results if r.score >= self.score_threshold]

    def redact(self, text: str) -> PIIResult:
        """
        Detect and redact PII from text.

        Args:
            text: Text to process

        Returns:
            PIIResult with original and redacted text
        """
        # Detect PII
        findings = self.detect(text)

        if not findings:
            return PIIResult(
                original_text=text,
                redacted_text=text,
                pii_detected=False,
                pii_count=0,
                pii_types=[],
                findings=[],
            )

        # Redact using mask operator
        operators = {
            entity: OperatorConfig(
                "mask",
                {"masking_char": self.redaction_char, "chars_to_mask": 100, "from_end": False},
            )
            for entity in self.entities
        }

        anonymized = self._anonymizer.anonymize(
            text=text,
            analyzer_results=findings,
            operators=operators,
        )

        # Extract unique PII types found
        pii_types = list(set(f.entity_type for f in findings))

        # Build findings summary
        findings_summary = [
            {
                "type": f.entity_type,
                "start": f.start,
                "end": f.end,
                "score": f.score,
            }
            for f in findings
        ]

        logger.debug(
            "pii_redacted",
            count=len(findings),
            types=pii_types,
        )

        return PIIResult(
            original_text=text,
            redacted_text=anonymized.text,
            pii_detected=True,
            pii_count=len(findings),
            pii_types=pii_types,
            findings=findings_summary,
        )

    def contains_pii(self, text: str) -> bool:
        """
        Quick check if text contains any PII.

        Args:
            text: Text to check

        Returns:
            True if PII detected
        """
        findings = self.detect(text)
        return len(findings) > 0

    def get_pii_summary(self, text: str) -> dict:
        """
        Get summary of PII in text without redacting.

        Args:
            text: Text to analyze

        Returns:
            Dictionary with PII summary
        """
        findings = self.detect(text)

        type_counts: dict[str, int] = {}
        for f in findings:
            type_counts[f.entity_type] = type_counts.get(f.entity_type, 0) + 1

        return {
            "total_pii_count": len(findings),
            "pii_by_type": type_counts,
            "has_pii": len(findings) > 0,
        }


class PIIFilterLight:
    """Lightweight PII filter using regex patterns (no ML models)."""

    import re

    PATTERNS = {
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "PHONE": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
        "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    }

    def __init__(self, redaction_char: str = "*") -> None:
        """Initialize lightweight PII filter."""
        self.redaction_char = redaction_char

    def redact(self, text: str) -> PIIResult:
        """Redact PII using regex patterns."""
        redacted = text
        findings = []
        pii_types = []

        for pii_type, pattern in self.PATTERNS.items():
            matches = list(pattern.finditer(text))
            if matches:
                pii_types.append(pii_type)
                for match in matches:
                    findings.append({
                        "type": pii_type,
                        "start": match.start(),
                        "end": match.end(),
                        "score": 1.0,
                    })
                    # Redact
                    replacement = self.redaction_char * (match.end() - match.start())
                    redacted = redacted[:match.start()] + replacement + redacted[match.end():]

        return PIIResult(
            original_text=text,
            redacted_text=redacted,
            pii_detected=len(findings) > 0,
            pii_count=len(findings),
            pii_types=pii_types,
            findings=findings,
        )
