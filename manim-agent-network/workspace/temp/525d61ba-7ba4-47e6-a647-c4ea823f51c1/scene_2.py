from manim import *

class Scene2(Scene):
    def construct(self):
        # STEP 1 — Title
        title = Text("Training", font_size=48).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # STEP 2 — Pipeline container
        pipe = Rectangle(height=6, width=1.5, stroke_width=2, color=WHITE).shift(LEFT * 4)
        self.play(Create(pipe))

        # STEP 3 — Labeled images sliding in
        cat_img = Square(side_length=0.7, color=GREEN, fill_opacity=0.4).move_to(LEFT * 5.5 + UP * 2.5)
        cat_lbl = Text("cat", font_size=20, color=GREEN).next_to(cat_img, DOWN, buff=0.1)
        dog_img = Square(side_length=0.7, color=ORANGE, fill_opacity=0.4).move_to(LEFT * 5.5 + UP * 1.5)
        dog_lbl = Text("dog", font_size=20, color=ORANGE).next_to(dog_img, DOWN, buff=0.1)
        self.play(FadeIn(cat_img, cat_lbl), FadeIn(dog_img, dog_lbl))

        # Animate drop
        self.play(
            cat_img.animate.scale(0.5).move_to(pipe.get_top() + UP * 0.1),
            cat_lbl.animate.scale(0.5).next_to(cat_img, DOWN, buff=0.05),
            dog_img.animate.scale(0.5).next_to(cat_img, DOWN, buff=0.2),
            dog_lbl.animate.scale(0.5).next_to(dog_img, DOWN, buff=0.05),
            run_time=1
        )

        # STEP 4 — Neural network layers
        layers = VGroup(*[
            Rectangle(width=2, height=0.3, stroke_width=1.5, color=BLUE, fill_opacity=0.2)
            for _ in range(3)
        ]).arrange(DOWN, buff=0.6).move_to(ORIGIN)
        self.play(Create(layers))

        # STEP 5 — Animated weights (lines)
        weights = VGroup()
        for i in range(2):
            for j in range(3):
                line = Line(
                    layers[i].get_right(),
                    layers[i + 1].get_left(),
                    stroke_width=2,
                    color=YELLOW
                )
                weights.add(line)
        self.play(Create(weights), run_time=1.5)

        # STEP 6 — Loss curve
        axes = Axes(x_range=[0, 100], y_range=[0, 2], x_length=3, y_length=2).to_edge(RIGHT).shift(UP * 1.5)
        loss_curve = axes.plot(lambda x: 2 * np.exp(-x / 20), color=RED)
        self.play(Create(axes), Create(loss_curve))

        # STEP 7 — Epoch counter
        epoch_text = Text("Epoch 1 → 100", font_size=28).next_to(axes, DOWN, buff=0.3)
        self.play(Write(epoch_text))

        # STEP 8 — Final accuracy label
        accuracy = Text("95 % ACCURATE", font_size=32, color=GREEN).next_to(layers, DOWN, buff=0.8)
        self.play(Write(accuracy))

        # STEP 9 — Fade out
        self.wait(2)
        self.play(FadeOut(Group(*self.mobjects)))
