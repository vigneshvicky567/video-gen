from manim import *
import numpy as np

class Scene3(Scene):
    def construct(self):
        # Title
        title = Text("Forward Pass in One Neuron", font_size=44).to_edge(UP)
        self.play(Write(title))
        self.wait(0.5)

        # Neuron body
        neuron = Circle(radius=0.8, color=ORANGE, stroke_width=4).shift(RIGHT*3)
        label = MathTex(r"\sigma", font_size=36).move_to(neuron.get_center())
        self.play(Create(neuron), Write(label))

        # Inputs
        x1 = MathTex("x_1", font_size=32).shift(LEFT*4 + UP*1.5)
        x2 = MathTex("x_2", font_size=32).shift(LEFT*4)
        x3 = MathTex("x_3", font_size=32).shift(LEFT*4 + DOWN*1.5)
        self.play(Write(x1), Write(x2), Write(x3))

        # Weights
        w1 = MathTex("w_1", font_size=28, color=YELLOW).next_to(x1, RIGHT, buff=0.3)
        w2 = MathTex("w_2", font_size=28, color=YELLOW).next_to(x2, RIGHT, buff=0.3)
        w3 = MathTex("w_3", font_size=28, color=YELLOW).next_to(x3, RIGHT, buff=0.3)
        self.play(Write(w1), Write(w2), Write(w3))

        # Lines from inputs
        l1 = Line(x1.get_right(), neuron.get_left(), buff=0.1)
        l2 = Line(x2.get_right(), neuron.get_left(), buff=0.1)
        l3 = Line(x3.get_right(), neuron.get_left(), buff=0.1)
        self.play(Create(l1), Create(l2), Create(l3))

        # Plus signs
        plus1 = MathTex("+", font_size=24, color=WHITE).move_to(l1.get_center() + UP*0.2)
        plus2 = MathTex("+", font_size=24, color=WHITE).move_to(l2.get_center() + UP*0.2)
        plus3 = MathTex("+", font_size=24, color=WHITE).move_to(l3.get_center() + UP*0.2)
        self.play(Write(plus1), Write(plus2), Write(plus3))

        # Bias bubble
        bias = MathTex("+b", font_size=32, color=GREEN).next_to(neuron, DOWN, buff=0.4)
        self.play(FadeIn(bias))

        # Sum arrow
        sum_arrow = Arrow(neuron.get_right(), neuron.get_right() + RIGHT*1.5, buff=0.1)
        sum_text = MathTex(r"\Sigma", font_size=32).next_to(sum_arrow, UP, buff=0.2)
        self.play(Create(sum_arrow), Write(sum_text))

        # Sigmoid curve
        sig_axes = Axes(x_range=[-6, 6], y_range=[0, 1.2], x_length=3, y_length=1.5, tips=False).next_to(sum_arrow, RIGHT, buff=0.3)
        sig_curve = sig_axes.plot(lambda x: 1/(1+np.exp(-x)), color=ORANGE, stroke_width=4)
        self.play(Create(sig_axes), Create(sig_curve))

        # Output value
        output = MathTex("0.73", font_size=36, color=ORANGE).next_to(sig_curve, RIGHT, buff=0.5)
        self.play(Write(output))
        self.play(output.animate.scale(1.3), run_time=0.4)
        self.play(output.animate.scale(1/1.3), run_time=0.4)
        self.wait(2)

        # Clean layout
        all_objs = VGroup(title, neuron, label, x1, x2, x3, w1, w2, w3, l1, l2, l3, plus1, plus2, plus3, bias, sum_arrow, sum_text, sig_axes, sig_curve, output)
        all_objs.scale_to_fit_width(12)
        all_objs.move_to(ORIGIN)
        self.wait(1)