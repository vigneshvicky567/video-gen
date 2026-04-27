from manim import *

class Scene3(Scene):
    def construct(self):
        # Title
        title = Text("Decoder Layer", font_size=48).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Mini encoder
        mini_enc = Rectangle(width=1.2, height=3, color=BLUE, fill_opacity=0.4)
        mini_label = Text("Encoder", font_size=20).next_to(mini_enc, UP, 0.1)
        mini_group = VGroup(mini_enc, mini_label).shift(LEFT * 5)

        # Decoder bands
        band1 = Rectangle(width=4, height=0.8, color=YELLOW, fill_opacity=0.3)
        band1_lbl = Tex("Masked\\Self-Attn", font_size=24).next_to(band1, UP, 0.1)
        band1_grp = VGroup(band1, band1_lbl)

        band2 = Rectangle(width=4, height=0.8, color=WHITE, fill_opacity=0.2)
        band2_lbl = Tex("Add\\LayerNorm", font_size=24).next_to(band2, UP, 0.1)
        band2_grp = VGroup(band2, band2_lbl)

        band3 = Rectangle(width=4, height=0.8, color=ORANGE, fill_opacity=0.3)
        band3_lbl = Tex("Enc-Dec\\Attention", font_size=24).next_to(band3, UP, 0.1)
        band3_grp = VGroup(band3, band3_lbl)

        band4 = Rectangle(width=4, height=0.8, color=GREEN, fill_opacity=0.3)
        band4_lbl = Tex("Feed\\Forward", font_size=24).next_to(band4, UP, 0.1)
        band4_grp = VGroup(band4, band4_lbl)

        decoder_stack = VGroup(band1_grp, band2_grp, band3_grp, band4_grp)
        decoder_stack.arrange(DOWN, buff=0.4)
        decoder_stack.next_to(mini_group, RIGHT, buff=2)

        # Mask overlay
        mask = Polygon(
            band1.get_corner(UL),
            band1.get_corner(UR),
            band1.get_corner(DR),
            band1.get_corner(DL),
            fill_color=GRAY,
            fill_opacity=0.5,
            stroke_width=0
        )
        mask.rotate(PI / 4, about_point=band1.get_center())
        mask.scale(0.7)

        # Arrows
        arrows = VGroup(*[
            Arrow(mini_enc.get_right(), band3.get_left(), buff=0.1, color=YELLOW, stroke_width=2)
            for _ in range(3)
        ])
        arrows.arrange(DOWN, buff=0.2)

        # Full layout
        full = VGroup(mini_group, decoder_stack, arrows)
        full.scale_to_fit_width(12)
        full.move_to(ORIGIN)

        # Animate
        self.play(FadeIn(mini_group))
        self.wait(0.5)
        self.play(FadeIn(decoder_stack))
        self.wait(0.5)
        self.play(band1.animate.set_fill(YELLOW, 0.6), FadeIn(mask))
        self.wait(1)
        self.play(band1.animate.set_fill(YELLOW, 0.3), FadeOut(mask))
        self.play(band2.animate.set_fill(WHITE, 0.5))
        self.wait(0.5)
        self.play(band2.animate.set_fill(WHITE, 0.2))
        self.play(band3.animate.set_fill(ORANGE, 0.6), *[GrowArrow(a) for a in arrows])
        self.wait(1)
        self.play(band3.animate.set_fill(ORANGE, 0.3))
        self.play(band4.animate.set_fill(GREEN, 0.6))
        self.wait(0.5)
        self.play(band4.animate.set_fill(GREEN, 0.3))

        # Collapse
        decoder_label = Text("Decoder 1", font_size=36)
        decoder_box = SurroundingRectangle(decoder_label, color=WHITE, buff=0.3)
        final_group = VGroup(decoder_label, decoder_box).move_to(ORIGIN)
        self.play(
            FadeOut(mini_group),
            FadeOut(arrows),
            FadeOut(decoder_stack),
            FadeIn(final_group)
        )
        self.wait(2)