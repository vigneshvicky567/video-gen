from manim import *

class Scene5(Scene):
    def construct(self):
        # Step 1: Title
        title = Text("Transformer", font_size=48).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Step 2: Build 6 encoders and 6 decoders as rectangles
        encoders = VGroup(*[Rectangle(width=1.2, height=3, color=BLUE, fill_opacity=0.3) for _ in range(6)])
        decoders = VGroup(*[Rectangle(width=1.2, height=3, color=GREEN, fill_opacity=0.3) for _ in range(6)])
        
        encoders.arrange(RIGHT, buff=0.3).shift(LEFT * 4)
        decoders.arrange(RIGHT, buff=0.3).shift(RIGHT * 4)
        
        full = VGroup(encoders, decoders)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)

        self.play(FadeIn(encoders), FadeIn(decoders))
        self.wait(0.5)

        # Step 3: Pulse animation
        pulse = Circle(radius=0.2, color=WHITE, fill_opacity=1)
        pulse.move_to(encoders[0].get_left() + LEFT * 0.5)

        # Animate pulse through encoders
        for i, enc in enumerate(encoders):
            self.play(pulse.animate.move_to(enc.get_center()), run_time=0.4)
            self.play(enc.animate.set_fill(WHITE, 0.6), run_time=0.2)
            self.play(enc.animate.set_fill(BLUE, 0.3), run_time=0.2)

        # Jump to decoder 6 and move backward
        self.play(pulse.animate.move_to(decoders[-1].get_right() + RIGHT * 0.5), run_time=0.5)
        for dec in reversed(decoders):
            self.play(pulse.animate.move_to(dec.get_center()), run_time=0.4)
            self.play(dec.animate.set_fill(WHITE, 0.6), run_time=0.2)
            self.play(dec.animate.set_fill(GREEN, 0.3), run_time=0.2)

        self.play(FadeOut(pulse))

        # Step 4: Tilt and wireframe
        self.play(full.animate.rotate(PI / 12, axis=UP + OUT), run_time=1.5)
        wireframe = full.copy()
        wireframe.set_stroke(WHITE, 2).set_fill(opacity=0)
        self.play(Transform(full, wireframe), FadeOut(title))
        
        label = Text("Transformer", font_size=36).next_to(full, DOWN)
        self.play(Write(label))
        self.wait(2)

        # Fade to black
        self.play(FadeOut(full), FadeOut(label))
        self.wait(1)
