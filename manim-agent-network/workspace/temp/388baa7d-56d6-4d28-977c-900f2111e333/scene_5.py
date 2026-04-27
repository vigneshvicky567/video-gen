from manim import *

class Scene5(Scene):
    def construct(self):
        # Initial sentence tokens (four updated vectors)
        tokens = VGroup(*[
            Rectangle(height=1.5, width=0.8, color=WHITE, fill_opacity=0.2)
            .set_stroke(WHITE, 2)
            .add(Text(f"t{i+1}", font_size=24).move_to(ORIGIN))
            for i in range(4)
        ]).arrange(RIGHT, buff=0.4).shift(UP*0.5)

        # Shimmer effect
        self.play(*[t.animate.set_fill(WHITE, 0.5) for t in tokens])
        self.play(*[t.animate.set_fill(WHITE, 0.2) for t in tokens])

        # Split into 8 heads per token
        heads_per_token = VGroup()
        colors = [RED, ORANGE, YELLOW, GREEN, TEAL, BLUE, PURPLE, PINK]
        head_width = 0.8 / 8
        for token in tokens:
            heads = VGroup(*[
                Rectangle(height=1.5, width=head_width, color=colors[i], fill_opacity=0.6)
                .set_stroke(colors[i], 2)
                .next_to(token, DOWN, buff=0.1)
                for i in range(8)
            ])
            heads_per_token.add(heads)

        # Animate split
        anims = []
        for token, heads in zip(tokens, heads_per_token):
            for i, head in enumerate(heads):
                head.move_to(token.get_center())
                anims.append(TransformFromCopy(token, head))
        self.play(*anims, lag_ratio=0.05)
        self.wait(0.5)

        # Collapse heads into narrow bars and stack
        stacked_heads = VGroup()
        for heads in heads_per_token:
            stacked = heads.copy()
            stacked.arrange(RIGHT, buff=0)
            stacked_heads.add(stacked)
        stacked_heads.arrange(RIGHT, buff=0.4).move_to(DOWN*1.5)
        self.play(
            *[Transform(heads, stacked) for heads, stacked in zip(heads_per_token, stacked_heads)],
            FadeOut(tokens)
        )

        # Linear projection matrix W_O
        w_o = Rectangle(height=1.5, width=0.5, color=WHITE, fill_opacity=0.1)
        w_o.set_stroke(WHITE, 2)
        w_o_label = Text("W_O", font_size=32).move_to(w_o.get_center())
        w_o_group = VGroup(w_o, w_o_label).next_to(stacked_heads, RIGHT, buff=0.8)
        self.play(FadeIn(w_o_group))

        # Unified embedding bar
        unified = Rectangle(height=1.5, width=0.8, color=WHITE, fill_opacity=0.3)
        unified.set_stroke(WHITE, 2)
        unified.next_to(w_o_group, RIGHT, buff=0.8)
        self.play(
            TransformFromCopy(stacked_heads, unified),
            run_time=1.5
        )

        # Camera pull back to show full sentence with halos
        final_tokens = VGroup(*[
            Rectangle(height=1.5, width=0.8, color=WHITE, fill_opacity=0.2)
            .set_stroke(WHITE, 2)
            .add(Text(f"t{i+1}", font_size=24).move_to(ORIGIN))
            for i in range(4)
        ]).arrange(RIGHT, buff=0.4).to_edge(UP, buff=1)
        halos = VGroup(*[
            Circle(radius=0.6, color=color, fill_opacity=0.2)
            .move_to(token.get_center())
            for token, color in zip(final_tokens, [RED, GREEN, BLUE, YELLOW])
        ])
        title = Text("Multi-Head Self-Attention", font_size=48).to_edge(UP, buff=0.2)
        self.play(
            FadeOut(stacked_heads),
            FadeOut(w_o_group),
            FadeOut(unified),
            FadeIn(final_tokens),
            FadeIn(halos),
            FadeIn(title),
            run_time=2
        )

        # Gentle zoom out and fade to black
        self.play(
            *[t.animate.scale(0.8) for t in final_tokens],
            *[h.animate.scale(0.8) for h in halos],
            title.animate.scale(0.8),
            run_time=2
        )
        self.play(FadeOut(VGroup(*final_tokens, *halos, title)))
        self.wait(0.5)