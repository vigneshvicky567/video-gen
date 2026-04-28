from manim import *

class Scene3(Scene):
    def construct(self):
        # Title
        title = Text("Logarithmic Speed", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Array boxes
        values = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]
        boxes = VGroup(*[
            Square(side_length=0.8, color=WHITE).add(Text(str(v), font_size=28))
            for v in values
        ])
        boxes.arrange(RIGHT, buff=0)
        boxes.next_to(title, DOWN, buff=0.8)
        self.play(FadeIn(boxes))
        self.wait(0.5)

        # Highlight active slice 9-14 (indices 1-6)
        active = VGroup(*boxes[1:7])
        active_rect = SurroundingRectangle(active, color=YELLOW, buff=0.1)
        self.play(Create(active_rect))
        self.wait(0.5)

        # Middle box (index 11 → value 12 → boxes[3])
        mid_box = boxes[3]
        mid_box[0].set_fill(ORANGE, opacity=0.8)
        self.play(Indicate(mid_box, scale_factor=1.2))
        self.wait(0.5)

        # Green translucent overlay shrinking
        green_overlay = Rectangle(
            width=active.width,
            height=active.height * 1.2,
            fill_color=GREEN,
            fill_opacity=0.3,
            stroke_width=0
        ).move_to(active.get_center())
        self.play(FadeIn(green_overlay))

        # Text overlay n → n/2 → n/4
        formula = MathTex("n", "\rightarrow", "n/2", "\rightarrow", "n/4", font_size=36)
        formula.next_to(active, DOWN, buff=0.8)
        self.play(Write(formula[0]))
        self.wait(0.3)

        # First shrink to half
        half_width = green_overlay.width / 2
        self.play(
            green_overlay.animate.set(width=half_width, center=active.get_left() + RIGHT * half_width / 2),
            Write(formula[2])
        )
        self.wait(0.3)

        # Second shrink to quarter
        quarter_width = half_width / 2
        self.play(
            green_overlay.animate.set(width=quarter_width, center=active.get_left() + RIGHT * quarter_width / 2),
            Write(formula[4])
        )
        self.wait(1)

        # Clean grouping and centering
        full = VGroup(title, boxes, active_rect, green_overlay, formula)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.wait(2)
