"""Exact JSON character accounting including the response's own budget metadata."""

import json
from dataclasses import asdict


class JsonBudget:
    @staticmethod
    def serialize(payload: dict, max_chars: int) -> str:
        payload["budget"] = {"unit": "json_characters", "limit": max_chars, "used": 0}
        for _ in range(8):
            result = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=asdict)
            size = len(result)
            if payload["budget"]["used"] == size:
                return result
            payload["budget"]["used"] = size
        raise RuntimeError("Could not determine the serialized JSON budget")
