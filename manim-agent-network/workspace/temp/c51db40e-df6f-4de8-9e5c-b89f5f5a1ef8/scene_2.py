from manim import *

class Scene2(Scene):
    def construct(self):
        # Title
        title = Text("Scaled Attention", font_size=36).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Formula step-by-step
        q = MathTex(r"Q", color=BLUE)
        k = MathTex(r"K^T", color=GREEN)
        v = MathTex(r"V", color=RED)
        
        trio = VGroup(q, k, v).arrange(RIGHT, buff=1.2)
        trio.scale_to_fit_width(8).move_to(ORIGIN)
        self.play(FadeIn(trio, shift=UP))
        self.wait(0.5)

        # QK^T
        qk = MathTex(r"QK^T", color=YELLOW)
        self.play(TransformFromCopy(q, qk), TransformFromCopy(k, qk))
        self.wait(0.3)

        # Scale
        scale = MathTex(r"/\sqrt{d_k}")
        self.play(FadeIn(scale, shift=LEFT))
        self.wait(0.3)

        # Softmax
        sm = MathTex(r"\text{softmax}", color=WHITE)
        self.play(Write(sm))
        self.wait(0.3)

        # Probability
        p = MathTex(r"p", color=PURPLE)
        self.play(TransformFromCopy(sm, p))
        self.wait(0.3)

        # V
        v2 = v.copy()
        self.play(v2.animate.next_to(p, RIGHT, buff=0.2))
        self.wait(0.3)

        # Output
        out = MathTex(r"\text{Output}", color=PURPLE)
        self.play(TransformFromCopy(p, out), TransformFromCopy(v2, out))
        self.wait(0.3)

        # Flash probs
        probs = MathTex(r"0.5,0.3,0.2", color=YELLOW, font_size=28).next_to(p, DOWN, buff=0.3)
        self.play(FadeIn(probs, shift=UP), run_time=0.5)
        self.play(FadeOut(probs), run_time=0.5)

        # Compact box
        all_parts = VGroup(qk, scale, sm, p, v2, out)
        all_parts.generate_target()
        all_parts.target.arrange(RIGHT, buff=0.2).scale_to_fit_width(10).move_to(ORIGIN)
        self.play(MoveToTarget(all_parts), FadeOut(q), FadeOut(k), FadeOut(v))
        self.wait(0.3)

        box = SurroundingRectangle(all_parts, buff=0.15, color=WHITE)
        label = Text("Self-Attention", font_size=28).next_to(box, DOWN, buff=0.2)
        self.play(Create(box), Write(label))
        self.wait(2)