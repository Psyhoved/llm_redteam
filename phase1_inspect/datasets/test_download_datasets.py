import importlib.util
import io
import tempfile
import unittest
from collections import OrderedDict
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from datasets.exceptions import DatasetNotFoundError


MODULE_PATH = Path(__file__).with_name("download_datasets.py")
SPEC = importlib.util.spec_from_file_location("download_datasets", MODULE_PATH)
download_datasets = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(download_datasets)


class DownloadDatasetsTests(unittest.TestCase):
    def test_run_downloads_only_requested_dataset(self):
        called = []

        registry = OrderedDict(
            [
                ("advbench", {"label": "AdvBench", "handler": lambda: called.append("advbench")}),
                ("wildjailbreak", {"label": "WildJailbreak", "handler": lambda: called.append("wildjailbreak")}),
            ]
        )

        with patch.object(download_datasets, "DATASET_SPECS", registry, create=True):
            summary = download_datasets.run_downloads(["advbench"])

        self.assertEqual(called, ["advbench"])
        self.assertEqual(summary["downloaded"], ["advbench"])
        self.assertEqual(summary["skipped"], [])

    def test_run_downloads_skips_gated_datasets_with_message(self):
        def gated_handler():
            raise DatasetNotFoundError(
                "Dataset 'allenai/wildjailbreak' is a gated dataset on the Hub. "
                "You must be authenticated to access it."
            )

        registry = OrderedDict(
            [
                ("wildjailbreak", {"label": "WildJailbreak", "handler": gated_handler}),
            ]
        )

        stdout = io.StringIO()
        with patch.object(download_datasets, "DATASET_SPECS", registry, create=True):
            with redirect_stdout(stdout):
                summary = download_datasets.run_downloads(["wildjailbreak"])

        self.assertEqual(summary["downloaded"], [])
        self.assertEqual(summary["skipped"], ["wildjailbreak"])
        self.assertIn("requires authentication", stdout.getvalue().lower())

    def test_download_ukrf_saves_prompts_csv(self):
        content = b"Article,Chapter,Prompt,Section,category,subcategory\n"
        response = Mock(content=content)
        response.raise_for_status = Mock()

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(download_datasets, "DATASETS_DIR", Path(tmpdir)):
                with patch.object(download_datasets.requests, "get", return_value=response) as get:
                    download_datasets.download_ukrf()

            dest = Path(tmpdir) / "ukrf" / "prompts.csv"
            self.assertEqual(dest.read_bytes(), content)

        get.assert_called_once_with(
            "https://raw.githubusercontent.com/HiveTrace/HiveTraceRed/master/datasets/prompts.csv",
            timeout=30,
        )
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
