from manim import *

class Scene2(Scene):
    def construct(self):
        # STEP 1: Title
        title = Text("Encoder 1", font_size=48).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # STEP 2: Zoom-in rectangle (placeholder for Encoder 1)
        enc_rect = Rectangle(width=4, height=2, stroke_width=3, color=WHITE)
        self.play(Create(enc_rect))
        self.wait(0.3)

        # STEP 3: Expand rectangle to full diagram
        self.play(enc_rect.animate.scale(2.5).set_stroke(opacity=0), run_time=0.8)

        # STEP 4: Build inner diagram
        # 4a. Multi-Head Self-Attention band
        attn_label = Text("Multi-Head Self-Attention", font_size=28, color=YELLOW)
        attn_box = SurroundingRectangle(attn_label, color=YELLOW, buff=0.15)
        attn_band = VGroup(attn_label, attn_box)

        # 4b. Arrow + Add & LayerNorm
        arrow1 = Arrow(DOWN, buff=0.1, stroke_width=3)
        add_norm = Text("Add & LayerNorm", font_size=28)
        add_norm_box = SurroundingRectangle(add_norm, color=WHITE, buff=0.15)
        add_norm_band = VGroup(add_norm, add_norm_box)

        # 4c. Feed-Forward band
        ff_label = Text("Feed-Forward", font_size=28, color=GREEN)
        ff_box = SurroundingRectangle(ff_label, color=GREEN, buff=0.15)
        ff_band = VGroup(ff_label, ff_box)

        # Stack vertically
        diagram = VGroup(attn_band, VGroup(arrow1, add_norm_band), ff_band)
        diagram.arrange(DOWN, buff=0.4)
        diagram.scale_to_fit_width(10).move_to(ORIGIN)

        # STEP 5: Create 5-token grid for attention visualization
        tokens = VGroup(*[Square(side_length=0.4, color=BLUE) for _ in range(5)])
        tokens.arrange(RIGHT, buff=0.2)
        tokens.next_to(attn_band, UP, buff=0.5)

        # STEP 6: Animate bands sequentially
        self.play(FadeIn(attn_band, tokens))
        self.wait(0.3)

        # Animate attention lines
        lines = VGroup()
        for i in range(5):
            for j in range(5):
                if i != j:
                    line = Line(tokens[i].get_center(), tokens[j].get_center(), stroke_width=1.5, color=YELLOW)
                    lines.add(line)
        self.play(*[Create(l) for l in lines], run_time=1)
        self.play(*[FadeOut(l) for l in lines])

        self.play(FadeIn(arrow1, add_norm_band))
        self.wait(0.3)
        self.play(FadeIn(ff_band))
        self.wait(1)

        # STEP 7: Shrink back to Encoder 1
        full = VGroup(diagram, tokens)
        self.play(FadeOut(full), enc_rect.animate.scale(1/2.5).set_stroke(opacity=1))
        self.wait(1)
