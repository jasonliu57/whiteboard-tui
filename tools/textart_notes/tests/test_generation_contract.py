from __future__ import annotations

import tempfile
import unittest

from tools.textart_notes.core.manifest import write_result
from tools.textart_notes.core.models import CardDraft, RenderOptions, RenderResult
from tools.textart_notes.materialize_textart import load_plan


class GenerationContractTests(unittest.TestCase):
    def test_published_generation_is_consumed_as_a_materialization_plan(self) -> None:
        options = RenderOptions(theme="ascii", max_width=10, max_height=5)
        result = RenderResult(
            renderer="contract",
            theme="ascii",
            cards=(CardDraft("card-000", "A中", 3, 1, x=2, y=4),),
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest = write_result(result, options, directory)
            plan = load_plan(manifest, origin_x=10, origin_y=20)

        self.assertEqual(len(plan.cards), 1)
        self.assertEqual(plan.cards[0].payload, "A中\n".encode())
        self.assertEqual(
            (plan.cards[0].absolute_x, plan.cards[0].absolute_y),
            (12, 24),
        )


if __name__ == "__main__":
    unittest.main()
