from manim import *

class Scene3(Scene):
    def construct(self):
        # 1. Six coloured tokens in a compact row
        words = ["The", "cat", "sat", "on", "it", "tired"]
        colours = [BLUE, GREEN, RED, YELLOW, PURPLE, ORANGE]
        tokens = VGroup(*[
            Square(side_length=0.6, color=colours[i], fill_opacity=0.3)
            .add(Text(words[i], font_size=18).move_to([0,0,0]))
            .move_to([i*0.8 - 2.0, 2.5, 0])
            for i in range(6)
        ])
        self.play(FadeIn(tokens))

        # 2. 6×6 matrix of dots
        matrix = VGroup(*[
            Dot([j*0.4 - 1.0, -i*0.4 + 1.0, 0], radius=0.03)
            for i in range(6) for j in range(6)
        ])
        self.play(FadeIn(matrix))

        # 3. Replace dots with vertical bars whose height = score
        scores = [[0.1, 0.2, 0.1, 0.1, 0.8, 0.3],
                  [0.2, 0.3, 0.4, 0.1, 0.7, 0.2],
                  [0.1, 0.4, 0.5, 0.2, 0.6, 0.1],
                  [0.1, 0.1, 0.2, 0.6, 0.4, 0.1],
                  [0.1, 0.3, 0.2, 0.1, 0.5, 0.9],
                  [0.1, 0.2, 0.1, 0.1, 0.4, 0.7]]

        bars = VGroup()
        for i in range(6):
            for j in range(6):
                h = scores[i][j]
                bar = Rectangle(width=0.08, height=h*0.3, color=WHITE, fill_opacity=1)
                bar.move_to([j*0.4 - 1.0, -i*0.4 + 1.0, 0])
                bars.add(bar)

        anims = []
        for dot, bar in zip(matrix, bars):
            anims.append(Transform(dot, bar))
        self.play(LaggedStart(*anims, lag_ratio=0.05), run_time=2.5)

        # 4. Flash the (5,6) cell (row 5, col 6 → index 5*6+5 = 35)
        highlight = bars[35].copy().set_color(YELLOW).set_fill(YELLOW, 1)
        self.play(Indicate(highlight, scale_factor=1.8, color=YELLOW), run_time=1)
        self.wait(0.5)
        self.play(FadeOut(highlight))
        self.wait(1)