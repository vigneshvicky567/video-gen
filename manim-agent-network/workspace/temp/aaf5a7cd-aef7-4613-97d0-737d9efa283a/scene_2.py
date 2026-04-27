from manim import *

class Scene2(Scene):
    def construct(self):
        # Sentence on the left
        sentence = Text("The cat sat on the mat", font_size=36)
        sentence.to_edge(LEFT, buff=1.2)
        self.add(sentence)

        # Embedding grid for "cat" (3×5)
        emb_grid = VGroup(*[
            Square(side_length=0.35, color=WHITE, fill_opacity=0.8, fill_color=GRAY)
            for _ in range(15)
        ]).arrange_in_grid(rows=3, cols=5, buff=0.05)
        emb_label = Text("embedding", font_size=24).next_to(emb_grid, DOWN)
        emb_group = VGroup(emb_grid, emb_label).to_edge(RIGHT, buff=1.5)

        # Q, K, V grids
        q_grid = emb_grid.copy().set_color(PASTEL_BLUE)
        k_grid = emb_grid.copy().set_color(PASTEL_PINK)
        v_grid = emb_grid.copy().set_color(PASTEL_GREEN)

        q_label = MathTex(r"\text{Q} = \text{embedding} \cdot W_Q", font_size=28)
        k_label = MathTex(r"\text{K} = \text{embedding} \cdot W_K", font_size=28)
        v_label = MathTex(r"\text{V} = \text{embedding} \cdot W_V", font_size=28)

        q_group = VGroup(q_grid, q_label).arrange(DOWN, buff=0.2)
        k_group = VGroup(k_grid, k_label).arrange(DOWN, buff=0.2)
        v_group = VGroup(v_grid, v_label).arrange(DOWN, buff=0.2)

        q_group.next_to(emb_group, UP, buff=0.8).shift(LEFT*1.5)
        k_group.next_to(q_group, DOWN, buff=0.6)
        v_group.next_to(k_group, DOWN, buff=0.6)

        # Weight matrices
        wq_rect = Rectangle(height=1.2, width=0.6, color=PASTEL_BLUE, fill_opacity=0.3)
        wk_rect = Rectangle(height=1.2, width=0.6, color=PASTEL_PINK, fill_opacity=0.3)
        wv_rect = Rectangle(height=1.2, width=0.6, color=PASTEL_GREEN, fill_opacity=0.3)

        wq_label = MathTex(r"W_Q", font_size=24).move_to(wq_rect.get_center())
        wk_label = MathTex(r"W_K", font_size=24).move_to(wk_rect.get_center())
        wv_label = MathTex(r"W_V", font_size=24).move_to(wv_rect.get_center())

        wq_group = VGroup(wq_rect, wq_label).next_to(q_grid, RIGHT, buff=0.4)
        wk_group = VGroup(wk_rect, wk_label).next_to(k_grid, RIGHT, buff=0.4)
        wv_group = VGroup(wv_rect, wv_label).next_to(v_grid, RIGHT, buff=0.4)

        # Checkmarks
        check_q = Tex(r"\checkmark", color=GREEN, font_size=28).next_to(wq_group, RIGHT, buff=0.2)
        check_k = Tex(r"\checkmark", color=GREEN, font_size=28).next_to(wk_group, RIGHT, buff=0.2)
        check_v = Tex(r"\checkmark", color=GREEN, font_size=28).next_to(wv_group, RIGHT, buff=0.2)

        # Animation
        self.play(sentence.animate.shift(LEFT*3), run_time=1)
        self.play(FadeIn(emb_group))

        # Curved arrows from embedding to Q, K, V
        arrow_q = CurvedArrow(emb_grid.get_top(), q_grid.get_bottom(), angle=-PI/3, color=WHITE)
        arrow_k = CurvedArrow(emb_grid.get_right(), k_grid.get_left(), angle=-PI/3, color=WHITE)
        arrow_v = CurvedArrow(emb_grid.get_bottom(), v_grid.get_top(), angle=-PI/3, color=WHITE)

        self.play(GrowArrow(arrow_q), GrowArrow(arrow_k), GrowArrow(arrow_v))
        self.play(FadeIn(q_group, k_group, v_group, wq_group, wk_group, wv_group))
        self.play(FadeIn(check_q, check_k, check_v))
        self.wait(1.5)