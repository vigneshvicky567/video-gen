from manim import *

class Scene2(Scene):
    def construct(self):
        # Title
        title = Text("Binary Search Step 1", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Build the array of 15 rounded-rect boxes
        boxes = VGroup()
        labels = VGroup()
        indices = VGroup()
        for i in range(15):
            box = RoundedRectangle(height=1, width=1, corner_radius=0.1, color=WHITE, fill_opacity=0.2)
            label = Text(str(i + 1), font_size=32)
            idx = Text(str(i), font_size=20, color=GRAY)
            box.add(label.move_to(box.get_center()))
            boxes.add(box)
            labels.add(label)
            indices.add(idx)

        # Arrange horizontally
        boxes.arrange(RIGHT, buff=0.1)
        for idx, index_mob in enumerate(indices):
            index_mob.next_to(boxes[idx], DOWN, buff=0.1)

        full = VGroup(boxes, indices)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)

        self.play(FadeIn(full))
        self.wait(0.5)

        # Highlight middle (index 7, value 8)
        middle_index = 7
        middle_box = boxes[middle_index]
        middle_box.set_fill(YELLOW, opacity=0.8)
        arrow = Arrow(UP, middle_box.get_top(), buff=0.2, color=YELLOW)
        arrow_text = Text("middle", font_size=32, color=YELLOW).next_to(arrow, UP)
        self.play(
            middle_box.animate.set_fill(YELLOW, opacity=0.8),
            GrowArrow(arrow),
            FadeIn(arrow_text)
        )
        self.wait(0.5)

        # Fade out left and right halves
        left_half = VGroup(*boxes[:middle_index])
        right_half = VGroup(*boxes[middle_index + 1:])
        self.play(
            left_half.animate.set_fill(opacity=0.3),
            right_half.animate.set_fill(opacity=0.3),
            run_time=0.4
        )
        self.wait(2)
