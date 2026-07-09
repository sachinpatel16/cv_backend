import unittest
import numpy as np
from services.ai.people_analytics import LineCrossingCounter

class TestLineCrossingCounter(unittest.TestCase):
    def test_vertical_line_left_to_right(self):
        # A vertical line from (100, 0) to (100, 100)
        # Normal vector points to Left (-1, 0). 
        # Left of line is IN (side=1), Right of line is OUT (side=-1).
        counter = LineCrossingCounter([100, 0], [100, 100])
        
        # Test crossing from Right to Left (OUT to IN -> "in")
        self.assertFalse(counter.update(1, (120, 50))) # armed OUT (side=-1)
        res = counter.update(1, (80, 50))              # crossed IN (side=1)
        self.assertEqual(res, "in")
        self.assertEqual(counter.in_count, 1)
        self.assertEqual(counter.out_count, 0)
        
        # Test crossing from Left to Right (IN to OUT -> "out")
        self.assertFalse(counter.update(2, (80, 50)))  # armed IN (side=1)
        res = counter.update(2, (120, 50))             # crossed OUT (side=-1)
        self.assertEqual(res, "out")
        self.assertEqual(counter.in_count, 1)
        self.assertEqual(counter.out_count, 1)

    def test_vertical_line_flipped(self):
        # Swap start and end points of the vertical line
        # Line from (100, 100) to (100, 0).
        # Normal vector points to Right (1, 0).
        # Right of line is IN (side=1), Left of line is OUT (side=-1).
        counter = LineCrossingCounter([100, 100], [100, 0])
        
        # Test crossing from Left to Right (OUT to IN -> "in")
        self.assertFalse(counter.update(1, (80, 50)))  # armed OUT (side=-1)
        res = counter.update(1, (120, 50))             # crossed IN (side=1)
        self.assertEqual(res, "in")
        self.assertEqual(counter.in_count, 1)
        self.assertEqual(counter.out_count, 0)
        
        # Test crossing from Right to Left (IN to OUT -> "out")
        self.assertFalse(counter.update(2, (120, 50))) # armed IN (side=1)
        res = counter.update(2, (80, 50))              # crossed OUT (side=-1)
        self.assertEqual(res, "out")
        self.assertEqual(counter.in_count, 1)
        self.assertEqual(counter.out_count, 1)

    def test_horizontal_line_top_to_bottom(self):
        # A horizontal line from (0, 100) to (100, 100)
        # Normal vector points Down (0, 1). (Note: Y increases downwards in screen coordinates)
        # Down of line is IN (side=1), Up of line is OUT (side=-1).
        counter = LineCrossingCounter([0, 100], [100, 100])
        
        # Test crossing from Up to Down (OUT to IN -> "in")
        self.assertFalse(counter.update(1, (50, 80)))  # armed OUT (side=-1)
        res = counter.update(1, (50, 120))             # crossed IN (side=1)
        self.assertEqual(res, "in")
        
        # Test crossing from Down to Up (IN to OUT -> "out")
        self.assertFalse(counter.update(2, (50, 120))) # armed IN (side=1)
        res = counter.update(2, (50, 80))              # crossed OUT (side=-1)
        self.assertEqual(res, "out")

    def test_diagonal_line(self):
        # A diagonal line from (0, 0) to (100, 100)
        # Vector points down-right (1, 1). Normal points up-left (-0.7, 0.7)
        counter = LineCrossingCounter([0, 0], [100, 100])
        
        # Test crossing from down-right (OUT, side=-1) to up-left (IN, side=1)
        self.assertFalse(counter.update(1, (80, 20)))  # distance: 80 * -0.7 + 20 * 0.7 = -42 < 0 -> armed OUT
        res = counter.update(1, (20, 80))              # distance: 20 * -0.7 + 80 * 0.7 = 42 > 0 -> crossed IN
        self.assertEqual(res, "in")

if __name__ == "__main__":
    unittest.main()
