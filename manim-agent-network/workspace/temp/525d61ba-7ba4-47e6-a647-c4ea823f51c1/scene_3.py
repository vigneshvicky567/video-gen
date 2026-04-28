from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        # Title
        title = Text("Black-Box Trade-off", font_size=42).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # X-ray placeholder
        xray = Rectangle(width=3.5, height=4.5, fill_color=GRAY, fill_opacity=0.8, stroke_width=2)
        self.play(FadeIn(xray))
        self.wait(0.3)

        # Red outline + label
        outline = Rectangle(width=1.2, height=1.2, color=RED, stroke_width=4).move_to(xray.get_center()+UP*0.3+LEFT*0.2)
        label = Text("PNEUMONIA", color=RED, font_size=28).next_to(xray, UP, buff=0.2)
        self.play(Create(outline), Write(label))
        self.wait(0.3)

        # Neural net (fixed)
        neurons = VGroup(*[Dot(radius=0.04, color=YELLOW).shift(np.random.uniform(-2.5,2.5)*RIGHT + np.random.uniform(-2,2)*UP) for _ in range(40)])
        lines = VGroup()
        for _ in range(60):
            a, b = np.random.choice(neurons.submobjects, 2, replace=False)
            lines.add(Line(a.get_center(), b.get_center(), stroke_width=1, color=YELLOW_A, opacity=0.6))
        net = VGroup(neurons, lines).set_z_index(-1)
        self.play(FadeIn(net), run_time=1)
        self.wait(0.3)

        # Scale icon
        scale_bar = Line(LEFT*1.5, RIGHT*1.5, stroke_width=6)
        fulcrum = Triangle(fill_opacity=1, fill_color=WHITE, stroke_width=0).scale(0.2).rotate(180*DEGREES).move_to(scale_bar.get_center()+DOWN*0.1)
        left_pan = Square(side_length=0.4, color=GREEN).move_to(scale_bar.get_left()+LEFT*0.3+DOWN*0.5)
        right_pan = Square(side_length=0.4, color=BLUE).move_to(scale_bar.get_right()+RIGHT*0.3+DOWN*0.5)
        scale = VGroup(scale_bar, fulcrum, left_pan, right_pan).scale(0.7).to_edge(DOWN, buff=0.4)
        self.play(FadeIn(scale))

        acc_text = Text("High Acc", font_size=20, color=GREEN).next_to(left_pan, DOWN, buff=0.1)
        trans_text = Text("Low Trans", font_size=20, color=BLUE).next_to(right_pan, DOWN, buff=0.1)
        self.play(Write(acc_text), Write(trans_text))
        self.play(Rotate(scale, angle=0.2*PI, about_point=fulcrum.get_center()), run_time=1.5)
        self.wait(0.3)

        # Magnifying glass
        lens = Circle(radius=0.6, stroke_width=3, color=WHITE, fill_opacity=0.2).move_to(xray.get_center())
        handle = Line(lens.get_bottom(), lens.get_bottom()+DOWN*0.8, stroke_width=4, color=WHITE)
        glass = VGroup(lens, handle).set_z_index(1)
        self.play(FadeIn(glass))
        self.play(glass.animate.shift(RIGHT*1.5+UP*0.5), run_time=1)
        self.wait(0.3)

        # Fade out
        self.play(FadeOut(xray), FadeOut(outline), FadeOut(label), FadeOut(glass), FadeOut(scale), FadeOut(acc_text), FadeOut(trans_text))

        # Net to question
        question = MathTex(r"?", font_size=96, color=YELLOW)
        self.play(Transform(net, question.scale(0.1).move_to(ORIGIN)), run_time=1.5)
        self.play(FadeOut(net))
        self.wait(1)