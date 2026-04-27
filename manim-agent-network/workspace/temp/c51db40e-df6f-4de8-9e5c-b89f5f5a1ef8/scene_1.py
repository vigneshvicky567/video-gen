from manim import *

class Scene1(Scene):
    def construct(self):
        # Title
        title = Text("Token Path", font_size=36).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Token
        token = Circle(radius=0.35, color=BLUE, fill_opacity=0.8)
        label = Text("Token", font_size=24)
        token_group = VGroup(token, label).arrange(DOWN, buff=0.15)
        self.play(FadeIn(token_group))
        self.wait(0.5)

        # Path
        path = DashedLine(token.get_top(), token.get_top() + UP * 1.2, color=WHITE)
        self.play(Create(path))
        self.wait(0.3)

        # Arrows & labels
        q_arrow = Arrow(path.get_end(), path.get_end() + UP * 1 + LEFT * 1.2, buff=0.1, color=RED)
        k_arrow = Arrow(path.get_end(), path.get_end() + UP * 1, buff=0.1, color=GREEN)
        v_arrow = Arrow(path.get_end(), path.get_end() + UP * 1 + RIGHT * 1.2, buff=0.1, color=BLUE)

        q_lab = MathTex("Q", color=RED).next_to(q_arrow, UP, buff=0.1)
        k_lab = MathTex("K", color=GREEN).next_to(k_arrow, UP, buff=0.1)
        v_lab = MathTex("V", color=BLUE).next_to(v_arrow, UP, buff=0.1)

        arrows = VGroup(q_arrow, k_arrow, v_arrow, q_lab, k_lab, v_lab)
        self.play(Create(arrows))
        self.wait(0.5)

        # Matrices
        q_mat = MathTex(r"1\!\times\!d_k", color=RED).scale(0.7).next_to(q_lab, UP, buff=0.15)
        k_mat = MathTex(r"1\!\times\!d_k", color=GREEN).scale(0.7).next_to(k_lab, UP, buff=0.15)
        v_mat = MathTex(r"1\!\times\!d_v", color=BLUE).scale(0.7).next_to(v_lab, UP, buff=0.15)

        self.play(Transform(q_lab, q_mat), Transform(k_lab, k_mat), Transform(v_lab, v_mat))
        self.wait(0.5)

        # Braces
        q_brace = Brace(q_mat, DOWN, color=RED)
        k_brace = Brace(k_mat, DOWN, color=GREEN)
        v_brace = Brace(v_mat, DOWN, color=BLUE)
        self.play(Create(VGroup(q_brace, k_brace, v_brace)))
        self.wait(0.5)

        # Pulse token
        self.play(token.animate.scale(1.2).set_color(YELLOW), run_time=0.5)
        self.play(token.animate.scale(1 / 1.2).set_color(BLUE), run_time=0.5)
        self.wait(0.5)

        # Fit frame
        full = VGroup(*self.mobjects)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)
        self.wait(2)