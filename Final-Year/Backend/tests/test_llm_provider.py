"""Tests for Ollama model selection and missing-model errors."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ollama import ResponseError

from app.llm.provider import generate, generate_with_ollama


class OllamaModelSelectionTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "OLLAMA_MODEL": "qwen3:14b",
        "OLLAMA_NUM_PREDICT": "2048",
        "OLLAMA_NUM_CTX": "8192",
        "OLLAMA_RESEARCH_MODEL": "phi3:latest",
        "OLLAMA_RESEARCH_NUM_PREDICT": "512",
        "OLLAMA_RESEARCH_NUM_CTX": "4096",
    }, clear=True)
    @patch("app.llm.provider.Client")
    def test_research_uses_its_lower_output_budget(self, client_factory):
        client = client_factory.return_value
        client.chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content='{"ok": true}')
        )

        generate_with_ollama("Return concise JSON.", task="research")

        options = client.chat.call_args.kwargs["options"]
        self.assertEqual(client.chat.call_args.kwargs["model"], "phi3:latest")
        self.assertEqual(options["num_predict"], 512)
        self.assertEqual(options["num_ctx"], 4096)

    @patch.dict(os.environ, {
        "OLLAMA_MODEL": "qwen3:14b",
        "OLLAMA_RESEARCH_MODEL": "phi3:latest",
    }, clear=True)
    @patch("app.llm.provider.Client")
    def test_proposals_keep_the_primary_qwen_model(self, client_factory):
        client = client_factory.return_value
        client.chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content='{"ok": true}')
        )

        generate_with_ollama("Return proposal JSON.", task="proposal")

        self.assertEqual(client.chat.call_args.kwargs["model"], "qwen3:14b")

    @patch.dict(os.environ, {
        "OLLAMA_MODEL": "qwen3:14b",
        "OLLAMA_TIMEOUT_SECONDS": "600",
        "OLLAMA_NUM_CTX": "8192",
        "OLLAMA_NUM_PREDICT": "2048",
        "OLLAMA_KEEP_ALIVE": "10m",
    }, clear=True)
    @patch("app.llm.provider.Client")
    def test_configures_timeout_output_budget_and_model_keep_alive(self, client_factory):
        client = client_factory.return_value
        client.chat.return_value = SimpleNamespace(
            message=SimpleNamespace(content='{"ok": true}')
        )

        self.assertEqual(generate_with_ollama("Return JSON."), '{"ok": true}')
        client_factory.assert_called_once_with(timeout=600.0)
        call = client.chat.call_args.kwargs
        self.assertEqual(call["model"], "qwen3:14b")
        self.assertEqual(call["options"]["num_predict"], 2048)
        self.assertEqual(call["keep_alive"], "10m")

    @patch.dict(os.environ, {}, clear=True)
    @patch("app.llm.provider.Client")
    def test_missing_default_uses_installed_qwen3_model(self, client_factory):
        client = client_factory.return_value
        client.chat.side_effect = [
            ResponseError("model 'qwen3:14b' not found", 404),
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),
        ]
        client.list.return_value = SimpleNamespace(models=[
            SimpleNamespace(model="qwen3:14b"),
            SimpleNamespace(model="mistral:latest"),
        ])

        self.assertEqual(generate_with_ollama("Return JSON."), '{"ok": true}')
        self.assertEqual(client.chat.call_args_list[0].kwargs["model"], "qwen3:14b")
        self.assertEqual(client.chat.call_args_list[1].kwargs["model"], "qwen3:14b")

    @patch.dict(os.environ, {}, clear=True)
    @patch("app.llm.provider.Client")
    def test_missing_default_prefers_installed_lightweight_model(self, client_factory):
        client = client_factory.return_value
        client.chat.side_effect = [
            ResponseError("model 'qwen3:14b' not found", 404),
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),
        ]
        client.list.return_value = SimpleNamespace(models=[
            SimpleNamespace(model="qwen3:14b"),
            SimpleNamespace(model="phi3:latest"),
        ])

        self.assertEqual(generate_with_ollama("Return JSON."), '{"ok": true}')
        self.assertEqual(client.chat.call_args_list[1].kwargs["model"], "phi3:latest")

    @patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:14b"}, clear=True)
    @patch("app.llm.provider.Client")
    def test_explicit_missing_model_reports_pull_command(self, client_factory):
        client_factory.return_value.chat.side_effect = ResponseError(
            "model 'qwen3:14b' not found", 404
        )

        with self.assertRaisesRegex(RuntimeError, "ollama pull qwen3:14b"):
            generate_with_ollama("Return JSON.")

    @patch.dict(os.environ, {}, clear=True)
    @patch("app.llm.provider.Client")
    def test_missing_default_without_qwen_model_reports_action(self, client_factory):
        client = client_factory.return_value
        client.chat.side_effect = ResponseError("model not found", 404)
        client.list.return_value = SimpleNamespace(models=[
            SimpleNamespace(model="mistral:latest"),
        ])

        with self.assertRaisesRegex(RuntimeError, "ollama pull qwen3:14b"):
            generate_with_ollama("Return JSON.")

    @patch.dict(os.environ, {}, clear=True)
    @patch("app.llm.provider.Client")
    def test_phi3_is_a_supported_fallback_without_qwen_models(self, client_factory):
        client = client_factory.return_value
        client.chat.side_effect = [
            ResponseError("model not found", 404),
            SimpleNamespace(message=SimpleNamespace(content='{"ok": true}')),
        ]
        client.list.return_value = SimpleNamespace(models=[
            SimpleNamespace(model="phi3:latest"),
        ])

        self.assertEqual(generate_with_ollama("Return JSON."), '{"ok": true}')
        self.assertEqual(client.chat.call_args_list[1].kwargs["model"], "phi3:latest")


class GroqProposalTests(unittest.TestCase):
    @patch.dict(os.environ, {
        "LLM_PROVIDER": "hybrid",
        "RESEARCH_PROVIDER": "ollama",
        "PROPOSAL_PROVIDER": "groq",
        "GROQ_API_KEY": "fixture-key",
        "GROQ_MODEL": "openai/gpt-oss-120b",
        "GROQ_TIMEOUT_SECONDS": "45",
        "GROQ_MAX_TOKENS": "4096",
        "GROQ_REASONING_EFFORT": "low",
    }, clear=True)
    @patch("app.llm.provider.Groq")
    def test_proposal_uses_configured_groq_gpt_oss_model(self, groq_factory):
        client = groq_factory.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )

        self.assertEqual(generate("Return proposal JSON.", task="proposal"), '{"ok": true}')

        groq_factory.assert_called_once_with(
            api_key="fixture-key", timeout=45.0, max_retries=0
        )
        call = client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["model"], "openai/gpt-oss-120b")
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual(call["max_completion_tokens"], 4096)
        self.assertEqual(call["reasoning_effort"], "low")

    @patch.dict(os.environ, {
        "LLM_PROVIDER": "hybrid",
        "PROPOSAL_PROVIDER": "groq",
        "GROQ_API_KEY": "fixture-key",
        "GROQ_MODEL": "openai/gpt-oss-120b",
    }, clear=True)
    @patch("app.llm.provider.Groq")
    def test_empty_groq_content_raises_actionable_error(self, groq_factory):
        client = groq_factory.return_value
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=""))]
        )

        with self.assertRaisesRegex(RuntimeError, "returned an empty response"):
            generate("Return proposal JSON.", task="proposal")


if __name__ == "__main__":
    unittest.main()
