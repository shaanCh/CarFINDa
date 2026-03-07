"""
Reusable Gemini client wrapper for CarFINDa.

Uses the google-genai SDK (pip package: google-genai) to interact with
Google Gemini models. All generation methods are async.
"""

import json
import logging

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiClient:
    """Wrapper around Google Gemini API for CarFINDa."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate(
        self,
        prompt: str,
        system_instruction: str = "",
        temperature: float = 0.7,
    ) -> str:
        """Generate a text response from Gemini.

        Args:
            prompt: The user prompt / input text.
            system_instruction: Optional system-level instruction prepended to
                the conversation to steer model behaviour.
            temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).

        Returns:
            The model's text response.
        """
        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )
        return response.text

    async def generate_structured(
        self,
        prompt: str,
        system_instruction: str,
        response_schema: dict,
        temperature: float = 0.3,
    ) -> dict:
        """Generate a structured JSON response using Gemini's structured output.

        Uses ``response_mime_type="application/json"`` and ``response_schema``
        to guarantee the model returns valid JSON matching the provided schema.

        Args:
            prompt: The user prompt / input text.
            system_instruction: System-level instruction.
            response_schema: A JSON Schema dict describing the expected output.
            temperature: Sampling temperature (lower = more deterministic).

        Returns:
            Parsed JSON dict from the model response.
        """
        config = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        try:
            return json.loads(response.text)
        except json.JSONDecodeError:
            logger.error("Failed to parse Gemini structured response: %s", response.text)
            raise

    async def chat(
        self,
        messages: list[dict],
        system_instruction: str = "",
        temperature: float = 0.7,
    ) -> str:
        """Multi-turn chat completion.

        Args:
            messages: Conversation history as a list of dicts, each with
                ``role`` ("user" or "model") and ``content`` (str).
            system_instruction: Optional system instruction.
            temperature: Sampling temperature.

        Returns:
            The model's text reply to the latest message.
        """
        # Build Contents list from the message history.
        contents = []
        for msg in messages:
            role = msg["role"]  # "user" or "model"
            text = msg["content"]
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=text)],
                )
            )

        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )
        return response.text
