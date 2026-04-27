from manim import *

class Scene4(Scene):
    def construct(self):
        # STEP 1 – Title
        title = Text("Feed-Forward & Stack", font_size=42).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # STEP 2 – Purple vector (from Scene 3)
        purple_vec = Arrow(LEFT, RIGHT, buff=0, color=PURPLE, stroke_width=6)
        purple_vec.scale(0.8).shift(LEFT * 3)
        self.play(GrowArrow(purple_vec))
        self.wait(0.3)

        # STEP 3 – Feed-Forward block
        ff_box = Rectangle(height=1.6, width=3.2, color=GRAY, fill_opacity=0.3)
        ff_label = Text("Feed-Forward 2048", font_size=28).move_to(ff_box.get_center())
        ff_group = VGroup(ff_box, ff_label).next_to(purple_vec, RIGHT, buff=0.4)
        self.play(FadeIn(ff_group, shift=RIGHT))
        self.wait(0.3)

        # STEP 4 – Linear → ReLU → Linear flash
        lin1 = Text("Linear", font_size=24).move_to(ff_box.get_left() + RIGHT * 0.6)
        relu = Text("ReLU", font_size=24).move_to(ff_box.get_center())
        lin2 = Text("Linear", font_size=24).move_to(ff_box.get_right() + LEFT * 0.6)
        self.play(FadeIn(lin1, shift=RIGHT), run_time=0.4)
        self.play(Transform(lin1, relu), run_time=0.4)
        self.play(Transform(lin1, lin2), run_time=0.4)
        self.play(FadeOut(lin1))

        # STEP 5 – Yellow output vector
        yellow_vec = Arrow(LEFT, RIGHT, buff=0, color=YELLOW, stroke_width=6)
        yellow_vec.scale(0.8).next_to(ff_group, RIGHT, buff=0.4)
        self.play(GrowArrow(yellow_vec))
        self.wait(0.3)

        # STEP 6 – Residual arrow
        residual = ArcBetweenPoints(
            purple_vec.get_end() + UP * 0.2,
            yellow_vec.get_start() + UP * 0.2,
            angle=-PI / 2,
            color=WHITE,
            stroke_width=4
        ).add_tip()
        self.play(Create(residual))
        self.wait(0.3)

        # STEP 7 – LayerNorm circle
        ln_circle = Circle(radius=0.4, color=BLUE, fill_opacity=0.3)
        ln_label = Text("LayerNorm", font_size=20).move_to(ln_circle.get_center())
        ln_group = VGroup(ln_circle, ln_label).next_to(ff_group, DOWN, buff=0.6)
        self.play(ln_group.animate.shift(UP * 0.6), run_time=0.5)
        self.wait(0.5)

        # STEP 8 – Fade out single block
        single = VGroup(purple_vec, ff_group, yellow_vec, residual, ln_group)
        self.play(FadeOut(single))

        # STEP 9 – Stack N identical blocks
        N = 6
        blocks = VGroup()
        for i in range(N):
            block = ff_box.copy().set_fill(opacity=0.2)
            block.scale(0.6)
            blocks.add(block)
        blocks.arrange(DOWN, buff=0.25).scale_to_fit_height(5)
        blocks.move_to(LEFT * 3)

        # STEP 10 – Encoder & Decoder labels
        encoder_label = Text("Encoder Stack", font_size=32).next_to(blocks, LEFT, buff=0.5)
        decoder_blocks = blocks.copy().next_to(blocks, RIGHT, buff=2)
        decoder_label = Text("Decoder Stack", font_size=32).next_to(decoder_blocks, RIGHT, buff=0.5)

        # STEP 11 – Masked attention icon on decoder
        mask = Line(
            decoder_blocks[0].get_corner(UL),
            decoder_blocks[0].get_corner(DR),
            color=RED,
            stroke_width=4
        )
        self.play(FadeIn(blocks), FadeIn(encoder_label))
        self.play(FadeIn(decoder_blocks), FadeIn(decoder_label))
        self.play(Create(mask))
        self.wait(2)
