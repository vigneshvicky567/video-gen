from manim import *

class Scene1(Scene):
    def construct(self):
        # Title
        title = Text("Transformer", font_size=48).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Input & Output blocks
        in_box = Square(side_length=1, color=BLUE, fill_opacity=0.8)
        in_lab = Text("Input", font_size=24)
        out_box = Square(side_length=1, color=RED, fill_opacity=0.8)
        out_lab = Text("Output", font_size=24)

        in_grp = VGroup(in_box, in_lab).arrange(DOWN, buff=0.2).shift(LEFT * 4)
        out_grp = VGroup(out_box, out_lab).arrange(DOWN, buff=0.2).shift(RIGHT * 4)

        self.play(FadeIn(in_grp), FadeIn(out_grp))
        self.wait(0.5)

        # Beam
        beam = Line(in_box.get_right(), out_box.get_left(), color=WHITE, stroke_width=4)
        self.play(Create(beam))
        self.wait(0.5)

        # Encoders
        encs = VGroup(*[
            Rectangle(width=1, height=0.3, color=TEAL, fill_opacity=0.8)
            for _ in range(6)
        ]).arrange(DOWN, buff=0.15).next_to(in_box, RIGHT, buff=1)

        # Decoders
        decs = VGroup(*[
            Rectangle(width=1, height=0.3, color=MAROON, fill_opacity=0.8)
            for _ in range(6)
        ]).arrange(UP, buff=0.15).next_to(out_box, LEFT, buff=1)

        self.play(FadeIn(encs), FadeIn(decs))
        self.wait(0.5)

        # Animate encoders
        for rect in encs:
            self.play(rect.animate.shift(DOWN * 0.2), run_time=0.3)
        self.wait(0.3)

        # Animate decoders
        for rect in decs:
            self.play(rect.animate.shift(UP * 0.2), run_time=0.3)
        self.wait(2)

        # Fit frame
        full = VGroup(title, in_grp, out_grp, beam, encs, decs)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.wait(1)