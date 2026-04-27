from manim import *

class Scene2(Scene):
    def construct(self):
        # ------------------------------------------------------------------
        # 1. Initial layout: four token circles with labels
        # ------------------------------------------------------------------
        tokens = VGroup(*[
            VGroup(Circle(radius=0.5, color=WHITE), Text(tok, font_size=24))
            .arrange(DOWN, buff=0.1)
            for tok in ["cat", "sat", "on", "mat"]
        ])
        tokens.arrange(RIGHT, buff=1.2).to_edge(UP, buff=1)
        self.add(tokens)

        # ------------------------------------------------------------------
        # 2. Zoom into the "cat" token
        # ------------------------------------------------------------------
        cat_token = tokens[0]
        self.play(
            cat_token.animate.scale(3).move_to(ORIGIN),
            tokens[1:].animate.scale(0.3).to_corner(UL, buff=0.3),
            run_time=2
        )

        # ------------------------------------------------------------------
        # 3. Create Q, K, V blocks sliding out from the circle
        # ------------------------------------------------------------------
        q_block = self.make_qkv_block("Q")
        k_block = self.make_qkv_block("K")
        v_block = self.make_qkv_block("V")
        qkv_group = VGroup(q_block, k_block, v_block).arrange(DOWN, buff=0.4)
        qkv_group.next_to(cat_token, RIGHT, buff=1)

        # Animate sliding from the circle
        for block in qkv_group:
            block.shift(LEFT * 4)
        self.play(
            *[block.animate.shift(RIGHT * 4) for block in qkv_group],
            run_time=1.5
        )

        # ------------------------------------------------------------------
        # 4. Brace with equations (using Text instead of MathTex)
        # ------------------------------------------------------------------
        brace = Brace(qkv_group, LEFT, buff=0.2)
        equations = VGroup(
            Text("xW_Q", font_size=28),
            Text("xW_K", font_size=28),
            Text("xW_V", font_size=28)
        ).arrange(DOWN, buff=0.6).next_to(brace, LEFT, buff=0.1)
        self.play(Create(brace), Write(equations), run_time=1)
        self.wait()

        # ------------------------------------------------------------------
        # 5. Dolly back: restore view and add mini QKV triplets
        # ------------------------------------------------------------------
        # Fade out brace & equations
        self.play(FadeOut(brace), FadeOut(equations), FadeOut(qkv_group))

        # Restore original positions and sizes
        self.play(
            cat_token.animate.scale(1/3).move_to(tokens[0].get_center()),
            tokens[1:].animate.scale(1/0.3).arrange(RIGHT, buff=1.2).to_edge(UP, buff=1),
            run_time=2
        )

        # Add mini QKV triplets beneath each token
        for token in tokens:
            mini_qkv = VGroup(*[
                self.make_qkv_mini() for _ in range(3)
            ]).arrange(DOWN, buff=0.1).scale(0.4).next_to(token, DOWN, buff=0.2)
            self.play(FadeIn(mini_qkv), run_time=0.5)
        self.wait()

    # ----------------------------------------------------------------------
    # Helper methods
    # ----------------------------------------------------------------------
    def make_qkv_block(self, label):
        rect = Rectangle(height=1.2, width=0.8, color=WHITE)
        label_mob = Text(label, font_size=28).move_to(rect.get_center())
        vector = self.make_vector().scale(0.6).next_to(label_mob, DOWN, buff=0.1)
        return VGroup(rect, label_mob, vector)

    def make_qkv_mini(self):
        rect = Rectangle(height=0.5, width=0.3, color=WHITE)
        vector = self.make_vector().scale(0.3).next_to(rect, DOWN, buff=0.05)
        return VGroup(rect, vector)

    def make_vector(self):
        return VGroup(*[
            Rectangle(height=0.2, width=0.15, color=BLUE, fill_opacity=0.8)
            for _ in range(3)
        ]).arrange(DOWN, buff=0.05)