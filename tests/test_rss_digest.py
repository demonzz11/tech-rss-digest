import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import rss_digest as app

TZ = ZoneInfo("Asia/Shanghai")
CONFIG = app.load_config(Path(__file__).parents[1] / "config.json")


def article(identifier="a", published=None, source="测试来源"):
    return {"id": identifier, "title": "科技新闻", "url": f"https://example.com/{identifier}",
            "source": source, "published_at": (published or datetime.now(TZ) - timedelta(hours=1)).isoformat(),
            "description": "可验证的 RSS 摘录"}


class PeriodTests(unittest.TestCase):
    def test_week_crosses_year_and_excludes_current_week(self):
        start, end, key = app.report_period("weekly", datetime(2026, 1, 5, 9, tzinfo=TZ))
        self.assertEqual(start.isoformat(), "2025-12-29T00:00:00+08:00")
        self.assertEqual(end.isoformat(), "2026-01-05T00:00:00+08:00")
        self.assertEqual(key, "2025-12-29_2026-01-04")

    def test_month_leap_year_and_year_boundary(self):
        start, end, key = app.report_period("monthly", datetime(2024, 3, 1, 10, tzinfo=TZ))
        self.assertEqual((end - start).days, 29)
        self.assertEqual(key, "2024-02")
        start, end, key = app.report_period("monthly", datetime(2026, 1, 1, 10, tzinfo=TZ))
        self.assertEqual(start.year, 2025)
        self.assertEqual(key, "2025-12")

    def test_daily_is_24_hours_even_when_scheduler_is_late(self):
        now = datetime(2026, 10, 3, 8, 37, tzinfo=TZ)
        start, end, key = app.report_period("daily", now)
        self.assertEqual(end - start, timedelta(hours=24))
        self.assertEqual(start.minute, 37)


class ArchiveTests(unittest.TestCase):
    def test_upsert_uses_local_day_and_exact_exclusive_end(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            start = datetime(2026, 10, 1, tzinfo=TZ)
            end = datetime(2026, 11, 1, tzinfo=TZ)
            items = [article("before", start - timedelta(seconds=1)), article("first", start),
                     article("last", end - timedelta(seconds=1)), article("after", end)]
            app.save_articles(root, items, TZ)
            app.save_articles(root, items, TZ)
            selected = app.archived_articles(root, start, end)
            self.assertEqual({item["id"] for item in selected}, {"first", "last"})
            self.assertTrue((root / "articles" / "2026-10-01.json").exists())
            self.assertEqual(len(app.read_json(root / "articles" / "2026-10-01.json")), 1)

    def test_canonical_url_strips_tracking_but_keeps_article_identity(self):
        self.assertEqual(app.canonical_url("https://EXAMPLE.com/story?id=12&utm_source=rss#top"),
                         "https://example.com/story?id=12")
        self.assertEqual(app.canonical_url("javascript:alert(1)"), "")
        self.assertEqual(app.canonical_url("https://user:password@example.com/"), "")

    def test_selection_does_not_allow_one_source_to_monopolize(self):
        items = [article(str(index), source="高产来源") for index in range(20)]
        items.append(article("other", source="另一个来源"))
        self.assertIn("other", {item["id"] for item in app.select_articles(items, 3)})

    def test_monthly_selection_covers_early_and_late_month(self):
        items = []
        for day in range(1, 31):
            for index in range(10):
                items.append(article(f"{day}-{index}", datetime(2026, 9, day, 12, tzinfo=TZ)))
        selected = app.select_articles(items, 60, TZ)
        self.assertEqual(len(selected), 60)
        self.assertEqual({app.iso_datetime(item["published_at"]).day for item in selected}, set(range(1, 31)))


class ProviderTests(unittest.TestCase):
    def test_feed_parsing_skips_undated_and_unsafe_links(self):
        now = datetime(2026, 10, 3, 8, tzinfo=TZ)
        xml = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Test</title>
        <item><title>Safe</title><link>https://example.com/story?utm_source=rss</link>
        <pubDate>Fri, 02 Oct 2026 23:00:00 GMT</pubDate><description>Summary</description></item>
        <item><title>Undated</title><link>https://example.com/undated</link></item>
        <item><title>Unsafe</title><link>javascript:alert(1)</link>
        <pubDate>Fri, 02 Oct 2026 23:00:00 GMT</pubDate></item></channel></rss>'''
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.iter_content.return_value = [xml]
        with patch.object(app.requests, "get", return_value=response):
            result = app.fetch_feed({"name": "Test", "url": "https://example.com/rss"}, CONFIG, now)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://example.com/story")

    def test_invalid_ai_references_are_dropped_and_html_is_escaped(self):
        now = datetime.now(TZ)
        generated = {"overview": "<script>alert(1)</script>", "highlights": [
            {"id": "invented", "summary": "虚构引用", "category": "AI"},
            {"id": "a", "summary": "<img onerror=alert(1)>", "category": "AI"},
            {"id": "a", "summary": "重复引用", "category": "AI"}]}
        response = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(generated)}}]}
        chat_config = {**CONFIG, "ai_api_format": "chat_completions"}
        with patch.object(app, "api_json", return_value=response):
            digest = app.summarize([article()], "daily", now - timedelta(days=1), now, chat_config, "test")
        self.assertEqual(len(digest["highlights"]), 1)
        title, html = app.render_report(digest, [article()], "daily", "test", now, now, 1, [])
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)

    def test_responses_request_and_output_ignore_reasoning_and_accept_json_fence(self):
        now = datetime.now(TZ)
        generated = {"overview": "中文概览", "highlights": [
            {"id": "a", "summary": "RSS 摘要", "category": "AI"}]}
        response = {"status": "completed", "output": [
            {"type": "reasoning", "summary": []},
            {"type": "message", "content": [{"type": "output_text", "text":
                '```json\n' + json.dumps(generated) + '\n```'}]}]}
        config = {**CONFIG, "ai_api_format": "responses", "ai_base_url": "http://example.com/v1/",
                  "ai_model": "gpt-5.5"}
        with patch.object(app, "api_json", return_value=response) as api:
            digest = app.summarize([article()], "daily", now - timedelta(days=1), now, config, "test")
        self.assertEqual(digest, generated)
        url, payload = api.call_args.args
        self.assertEqual(url, "http://example.com/v1/responses")
        self.assertEqual(payload["model"], "gpt-5.5")
        self.assertFalse(payload["store"])
        self.assertEqual(payload["input"][0]["content"][0]["type"], "input_text")
        self.assertNotIn("temperature", payload)
        self.assertNotIn("max_output_tokens", payload)
        self.assertEqual(api.call_args.kwargs["headers"]["originator"], "codex_cli_rs")
        self.assertEqual(api.call_args.kwargs["headers"]["Authorization"], "Bearer test")

    def test_responses_incomplete_is_not_sent_as_valid_digest(self):
        now = datetime.now(TZ)
        with patch.object(app, "api_json", return_value={"status": "incomplete", "output": []}):
            with self.assertRaises(app.DigestError):
                app.summarize([article()], "daily", now, now, {**CONFIG, "ai_api_format": "responses"}, "test")

    def test_pushplus_rejection_does_not_expose_response_secret(self):
        with patch.object(app, "api_json", return_value={"code": 600, "msg": "secret-key"}):
            with self.assertRaises(app.DigestError) as caught:
                app.push_report("title", "content", "secret-key")
        self.assertNotIn("secret-key", str(caught.exception))

    def test_pushplus_unverified_account_has_actionable_error(self):
        with patch.object(app, "api_json", return_value={"code": 905, "msg": "账户未进行实名认证"}):
            with self.assertRaises(app.DigestError) as caught:
                app.push_report("title", "content", "secret-key")
        self.assertIn("实名认证", str(caught.exception))
        self.assertNotIn("secret-key", str(caught.exception))

    def test_ntfy_validates_topic_and_sends_html(self):
        response = Mock(ok=True, status_code=200)
        with patch.object(app.requests, "post", return_value=response) as post:
            app.push_ntfy("科技日报", "<h2>摘要</h2>", "topic_secret_123", "https://ntfy.sh")
        self.assertEqual(post.call_args.args[0], "https://ntfy.sh/topic_secret_123")
        self.assertEqual(post.call_args.kwargs["headers"]["X-Format"], "html")
        self.assertEqual(post.call_args.kwargs["data"], "<h2>摘要</h2>".encode())

    def test_ntfy_rejects_unsafe_topic_without_network_request(self):
        with patch.object(app.requests, "post") as post:
            with self.assertRaises(app.DigestError):
                app.push_ntfy("title", "content", "topic/with/path", "https://ntfy.sh")
        post.assert_not_called()

    def test_push_timeout_is_not_retried(self):
        with patch.object(app.requests, "post", side_effect=app.requests.Timeout("secret-key")) as post:
            with self.assertRaises(app.DigestError) as caught:
                app.push_report("title", "content", "secret-key")
        self.assertEqual(post.call_count, 1)
        self.assertNotIn("secret-key", str(caught.exception))

    def test_model_discovery_uses_current_key_and_rejects_unavailable_model(self):
        response = Mock(ok=True)
        response.json.return_value = {"data": [{"id": "deepseek-chat"}]}
        with patch.object(app.requests, "get", return_value=response) as get:
            with self.assertRaises(app.DigestError):
                app.check_available_models({**CONFIG, "ai_model": "gpt-5.5"}, "current-key")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer current-key")

    def test_upstream_rate_limit_error_is_clear_without_echoing_secret(self):
        response = Mock(ok=False, status_code=429)
        response.json.return_value = {"error": {"message":
            "All available accounts are currently rate-limited. secret-key"}}
        with patch.object(app.requests, "post", return_value=response):
            with self.assertRaises(app.DigestError) as caught:
                app.api_json("http://example.com/v1/chat/completions", {})
        self.assertIn("上游账号均被限流", str(caught.exception))
        self.assertNotIn("secret-key", str(caught.exception))


@patch.object(app, "check_available_models", new=Mock())
class PipelineTests(unittest.TestCase):
    def args(self, root, **changes):
        test_config = root / "config.json"
        test_config.write_text(json.dumps({**CONFIG, "push_service": "pushplus"}), encoding="utf-8")
        values = dict(type="daily", config=test_config,
                      archive_dir=root / "archive", report_dir=root / "output",
                      dry_run=False, no_push=False, force=False)
        values.update(changes)
        return argparse.Namespace(**values)

    def test_failed_push_preserves_articles_and_retry_then_skips_sent_report(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(app.os.environ, {
                "DEEPSEEK_API_KEY": "fake-key", "PUSHPLUS_TOKEN": "fake-token"}):
            root = Path(temp)
            args = self.args(root)
            digest = {"overview": "测试概览", "highlights": [{"id": "a", "summary": "摘要", "category": "AI"}]}
            with patch.object(app, "collect_feeds", return_value=([article()], [])) as fetch, \
                    patch.object(app, "summarize", return_value=digest), \
                    patch.object(app, "push_report", side_effect=app.DigestError("拒绝")):
                with self.assertRaises(app.DigestError):
                    app.run(args)
            self.assertTrue(list((root / "archive" / "articles").glob("*.json")))
            report_file = next((root / "archive" / "reports" / "daily").glob("*.json"))
            self.assertIsNone(app.read_json(report_file)["sent_at"])
            with patch.object(app, "collect_feeds", return_value=([article()], [])), \
                    patch.object(app, "summarize", return_value=digest), \
                    patch.object(app, "push_report") as push:
                app.run(args)
                push.assert_called_once()
            self.assertTrue(app.read_json(report_file)["sent_at"])
            with patch.object(app, "collect_feeds") as fetch:
                app.run(args)
                fetch.assert_not_called()

    def test_dry_run_does_not_require_secrets_or_write_files(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(app.os.environ, {}, clear=True):
            root = Path(temp)
            with patch.object(app, "collect_feeds", return_value=([article()], [])), \
                    patch.object(app, "summarize") as ai, patch.object(app, "push_report") as push:
                app.run(self.args(root, dry_run=True))
            self.assertFalse((root / "archive").exists())
            self.assertFalse((root / "output").exists())
            ai.assert_not_called()
            push.assert_not_called()

    def test_weekly_can_use_archive_when_all_feeds_are_down(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(app.os.environ, {"DEEPSEEK_API_KEY": "fake-key"}):
            root = Path(temp)
            args = self.args(root, type="weekly", no_push=True)
            start, end, key = app.report_period("weekly", datetime.now(TZ))
            app.save_articles(args.archive_dir, [article(published=start + timedelta(days=1))], TZ)
            digest = {"overview": "周报", "highlights": [{"id": "a", "summary": "摘要", "category": "AI"}]}
            with patch.object(app, "collect_feeds", return_value=([], [source["name"] for source in CONFIG["feeds"]])), \
                    patch.object(app, "summarize", return_value=digest):
                app.run(args)
            self.assertTrue(list(args.report_dir.glob("*.html")))


if __name__ == "__main__":
    unittest.main()
