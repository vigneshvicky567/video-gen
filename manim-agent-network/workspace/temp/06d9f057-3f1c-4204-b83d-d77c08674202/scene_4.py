from manim import *

class Scene4(Scene):
    def construct(self):
        # Background
        self.camera.background_color = BLACK
        chalkboard = Rectangle(width=14, height=8, stroke_width=0, fill_color="#1a1a1a", fill_opacity=1)
        self.add(chalkboard)

        # Title
        title = Tex("Multi-Head Attention", font_size=40).to_edge(UP)
        self.play(Write(title))
        self.wait()

        # Formula
        formula = MathTex(r"A = \text{softmax}\Bigl(\frac{QK^T}{\sqrt{d_k}}\Bigr)V", font_size=36)
        formula.next_to(title, DOWN, buff=0.4)
        self.play(Write(formula))
        self.wait()

        # Matrices
        Q = Matrix([[r"q_{11}", r"q_{12}"], [r"q_{21}", r"q_{22}"]], color=BLUE).scale(0.4)
        K = Matrix([[r"k_{11}", r"k_{12}"], [r"k_{21}", r"k_{22}"]], color=GREEN).scale(0.4).rotate(PI/2)
        V = Matrix([[r"v_{11}", r"v_{12}"], [r"v_{21}", r"v_{22}"]], color=RED).scale(0.4)
        matrices = VGroup(Q, K, V).arrange(RIGHT, buff=0.5).next_to(formula, DOWN, buff=0.4)
        self.play(FadeIn(matrices))
        self.wait()

        # Single head highlight
        box = SurroundingRectangle(Q, color=YELLOW, buff=0.1)
        label = Tex("Single Head", font_size=28, color=YELLOW).next_to(box, UP, buff=0.1)
        self.play(Create(box), Write(label))
        self.wait()

        # Heatmap
        heat = Rectangle(width=1, height=1, fill_opacity=0.8).set_fill_by_checkerboard([BLUE_E, BLUE_A])
        heat.next_to(matrices, DOWN, buff=0.4)
        self.play(FadeIn(heat))
        self.wait()

        # Result
        arrow = Arrow(heat.get_bottom(), V.get_bottom(), color=WHITE, buff=0.1)
        res = Matrix([[r"a_{11}", r"a_{12}"], [r"a_{21}", r"a_{22}"]], color=GOLD).scale(0.4).next_to(V, DOWN, buff=0.4)
        self.play(GrowArrow(arrow), FadeIn(res))
        self.wait()

        # Clean single-head
        self.play(FadeOut(box), FadeOut(label), FadeOut(arrow), FadeOut(res))

        # Multi-head miniatures
        heads = VGroup()
        for i in range(4):
            q = Matrix([[r"q"]*2]*2, color=BLUE).scale(0.15)
            k = Matrix([[r"k"]*2]*2, color=GREEN).scale(0.15).rotate(PI/2)
            v = Matrix([[r"v"]*2]*2, color=RED).scale(0.15)
            trio = VGroup(q, k, v).arrange(RIGHT, buff=0.1)
            lbl = Tex(f"Head {i+1}", font_size=18).next_to(trio, DOWN, buff=0.1)
            heads.add(VGroup(trio, lbl))
        heads.arrange(RIGHT, buff=0.2).next_to(matrices, DOWN, buff=0.4)
        self.play(LaggedStart(*[FadeIn(h) for h in heads], lag_ratio=0.1))
        self.wait()

        # Concat output
        concat = Matrix([[r"h_1"], [r"h_2"], [r"h_3"], [r"h_4"]], color=GOLD).scale(0.4)
        concat_lbl = Tex("Multi-Head Output", font_size=28, color=GOLD).next_to(concat, UP)
        out = VGroup(concat_lbl, concat).arrange(DOWN, buff=0.15)
        self.play(heads.animate.scale(0.7).to_edge(LEFT), FadeIn(out))
        self.wait(2)

        # Fit everything
        all_objs = VGroup(title, formula, matrices, heat, heads, out)
        all_objs.scale_to_fit_width(12).center()
        self.wait()

        # Fade out
        self.play(FadeOut(all_objs))
        self.wait(0.5)