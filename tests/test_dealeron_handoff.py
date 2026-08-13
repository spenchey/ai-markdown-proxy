from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / "dealeron-discovery-handoff"
SITES = {
    "motorinnautogroup.com": "ai.motorinnautogroup.com",
    "motorinntoyotaofcarroll.com": "ai.motorinntoyotaofcarroll.com",
    "motorinnofcarroll.com": "ai.motorinnofcarroll.com",
}


class DealerOnDiscoveryHandoffTests(unittest.TestCase):
    def test_each_site_has_discovery_files_for_only_its_matching_host(self) -> None:
        all_hosts = set(SITES.values())
        for site, host in SITES.items():
            directory = HANDOFF / site
            for filename in ("llms.txt", "llms-full.txt", "robots-additions.txt"):
                self.assertTrue((directory / filename).is_file(), f"missing {site}/{filename}")
            discovery = "\n".join(
                (directory / filename).read_text(encoding="utf-8")
                for filename in ("llms.txt", "llms-full.txt")
            )
            self.assertIn(f"https://{host}/llms.txt", discovery)
            for other_host in all_hosts - {host}:
                self.assertNotIn(other_host, discovery)

    def test_crawler_policy_allows_search_and_blocks_training(self) -> None:
        for site in SITES:
            policy = (HANDOFF / site / "robots-additions.txt").read_text(encoding="utf-8")
            self.assertIn("User-agent: OAI-SearchBot\nAllow: /", policy)
            self.assertIn("User-agent: Claude-SearchBot\nAllow: /", policy)
            self.assertIn("User-agent: GPTBot\nDisallow: /", policy)
            self.assertIn("User-agent: ClaudeBot\nDisallow: /", policy)


if __name__ == "__main__":
    unittest.main()
