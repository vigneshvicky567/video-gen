from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        # Tokens
        q_tokens = ["Q_{\\text{the}}", "Q_{\\text{cat}}", "Q_{\\text{sat}}", "Q_{\\text{down}}"]
        k_tokens = ["K_{\\text{the}}", "K_{\\text{cat}}", "K_{\\text{sat}}", "K_{\\text{down}}"]

        # Build matrix grid
        rows = len(q_tokens)
        cols = len(k_tokens)
        cell_size = 1.2
        grid = VGroup()

        # Create cells
        for r in range(rows):
            for c in range(cols):
                rect = Square(side_length=cell_size, stroke_width=2, color=WHITE)
                rect.move_to(np.array([
                    c * cell_size - (cols - 1) * cell_size / 2,
                    -r * cell_size + (rows - 1) * cell_size / 2,
                    0
                ]))
                grid.add(rect)

        # Row labels
        row_labels = VGroup(*[
            MathTex(tok, font_size=28).next_to(grid[r * cols], LEFT, buff=0.3)
            for r, tok in enumerate(q_tokens)
        ])

        # Column labels
        col_labels = VGroup(*[
            MathTex(tok, font_size=28).next_to(grid[c], UP, buff=0.3)
            for c in range(cols)
        ])

        matrix_group = VGroup(grid, row_labels, col_labels).center()

        # Title
        title = MathTex(r"\text{Attention Scores}", font_size=40).to_edge(UP)
        self.play(FadeIn(matrix_group), FadeIn(title))
        self.wait(0.5)

        # Animate dot-products
        scores = {}
        for r in range(rows):
            for c in range(cols):
                cell = grid[r * cols + c]
                q_vec = MathTex("Q_{", q_tokens[r][9:-1], "}", font_size=28, color=BLUE)
                k_vec = MathTex("K_{", k_tokens[c][9:-1], "}", font_size=28, color=RED)
                dot_sym = MathTex(r"\cdot", font_size=36)
                q_vec.next_to(cell, UP, buff=0.1)
                k_vec.next_to(cell, UP, buff=0.1)
                dot_sym.move_to(cell.get_center())
                self.play(FadeIn(q_vec), FadeIn(k_vec), FadeIn(dot_sym), run_time=0.3)
                self.play(
                    q_vec.animate.move_to(cell.get_center()),
                    k_vec.animate.move_to(cell.get_center()),
                    dot_sym.animate.move_to(cell.get_center()),
                    run_time=0.3
                )
                score_val = np.random.uniform(0.5, 4.5)
                score = MathTex(f"{score_val:.2f}", font_size=28)
                score.move_to(cell.get_center())
                scores[(r, c)] = score_val
                self.play(Transform(VGroup(q_vec, k_vec, dot_sym), score), run_time=0.3)
        self.wait(0.5)

        # Softmax bracket and normalization
        bracket = Brace(matrix_group, DOWN, buff=0.2)
        softmax_text = MathTex(r"\text{Softmax}", font_size=32).next_to(bracket, DOWN, buff=0.2)
        self.play(matrix_group.animate.shift(DOWN * 1.5), title.animate.shift(DOWN * 1.5))
        self.play(GrowFromCenter(bracket), FadeIn(softmax_text))

        # Apply softmax and color cells
        total = sum(np.exp(v) for v in scores.values())
        for r in range(rows):
            for c in range(cols):
                cell = grid[r * cols + c]
                prob = np.exp(scores[(r, c)]) / total
                intensity = prob * 255
                color = rgb_to_color([0, intensity / 255, 0])
                self.play(cell.animate.set_fill(color, opacity=0.7), run_time=0.1)
        self.wait(2)