import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "host"))
import rxdiag_events as r


class T(unittest.TestCase):
    def test_truncated_records_ignored(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# c\n0.1 B,1,2\n0.2 C,1,2,x\n0.3 X,done\n")
        H, B, C, E, X = r.parse(f.name)
        self.assertEqual((B, C, X), ([], [], "X,done"))
        self.assertIn("error", r.summary(f.name))
        os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()
