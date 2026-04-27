from manim import *

class Scene1(Scene):
    def construct(self):
        self.camera.background_color = "#1e1e2e"
        sentence = Text("The cat sat on the mat because it was tired.", font="Monospace", font_size=36)
        sentence.set_color(WHITE)
        
        title = Text("Self-Attention Mechanism Explained", font_size=48, color=WHITE)
        title.to_edge(UP)
        
        self.add(sentence)
        words = sentence[0].split()
        for word in words:
            word.save_state()
        
        for word in words:
            self.play(word.animate.set_color(YELLOW), run_time=0.5)
            self.play(word.animate.set_color(WHITE), run_time=0.3)
        
        glow = Circle(radius=0.6, color=YELLOW, fill_opacity=0.3, stroke_width=0)
        glow.move_to(words[-1])
        self.play(FadeIn(glow), words[-1].animate.set_color(YELLOW))
        
        self.play(self.camera.frame.animate.scale(1.2), FadeIn(title), run_time=2)
        self.wait(2)