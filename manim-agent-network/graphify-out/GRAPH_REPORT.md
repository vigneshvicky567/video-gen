# Graph Report - "+C:\Users\thava\OneDrive\Desktop\video-gen\video-gen\manim-agent-network+"  (2026-04-12)

## Corpus Check
- Corpus is ~23,672 words - fits in a single context window. You may not need a graph.

## Summary
- 82 nodes · 107 edges · 18 communities detected
- Extraction: 79% EXTRACTED · 21% INFERRED · 0% AMBIGUOUS · INFERRED: 22 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Scene_1 Construct Scene_2|Scene_1 Construct Scene_2]]
- [[_COMMUNITY_Assemble_video Codegenoutput Generate_code|Assemble_video Codegenoutput Generate_code]]
- [[_COMMUNITY_Basemodel Generationrequest Jobstate|Basemodel Generationrequest Jobstate]]
- [[_COMMUNITY_Langgraphstate Scriptresponse Assemblerresponse|Langgraphstate Scriptresponse Assemblerresponse]]
- [[_COMMUNITY_Assembler_node Code_generator_node Post|Assembler_node Code_generator_node Post]]
- [[_COMMUNITY_Generate_espeak_fallback Generate_openai_tts Generate_voiceover|Generate_espeak_fallback Generate_openai_tts Generate_voiceover]]
- [[_COMMUNITY_Scene_4 Scene4 Construct|Scene_4 Scene4 Construct]]
- [[_COMMUNITY_Basesettings Settings Config|Basesettings Settings Config]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]
- [[_COMMUNITY_Init__|Init__]]

## God Nodes (most connected - your core abstractions)
1. `ScriptResponse` - 8 edges
2. `ScenePlan` - 7 edges
3. `JobState` - 7 edges
4. `health()` - 6 edges
5. `_post()` - 6 edges
6. `VoiceoverRequest` - 6 edges
7. `Scene1` - 6 edges
8. `CodeGeneratorRequest` - 5 edges
9. `VoiceoverResponse` - 5 edges
10. `Scene2` - 5 edges

## Surprising Connections (you probably didn't know these)
- `CodeGenOutput` --uses--> `CodeGeneratorRequest`  [INFERRED]
  services\code-generator\app\main.py → shared\schemas\requests.py
- `CodeGenOutput` --uses--> `CodeGeneratorResponse`  [INFERRED]
  services\code-generator\app\main.py → shared\schemas\responses.py
- `Generate TTS using OpenAI. Returns True if successful.` --uses--> `VoiceoverRequest`  [INFERRED]
  services\voiceover\app\main.py → shared\schemas\requests.py
- `Generate TTS using OpenAI. Returns True if successful.` --uses--> `VoiceoverResponse`  [INFERRED]
  services\voiceover\app\main.py → shared\schemas\responses.py
- `Fallback to espeak (last resort).` --uses--> `VoiceoverRequest`  [INFERRED]
  services\voiceover\app\main.py → shared\schemas\requests.py

## Communities

### Community 0 - "Scene_1 Construct Scene_2"
Cohesion: 0.12
Nodes (4): Scene, Scene1, Scene2, Scene3

### Community 1 - "Assemble_video Codegenoutput Generate_code"
Cohesion: 0.14
Nodes (2): CodeGenOutput, health()

### Community 2 - "Basemodel Generationrequest Jobstate"
Cohesion: 0.47
Nodes (9): BaseModel, GenerationRequest, JobState, ScenePlan, AssemblerRequest, CodeGeneratorRequest, ScriptWriterRequest, ValidatorRequest (+1 more)

### Community 3 - "Langgraphstate Scriptresponse Assemblerresponse"
Cohesion: 0.29
Nodes (8): LangGraphState, ScriptResponse, AssemblerResponse, CodeGeneratorResponse, ScriptWriterResponse, ValidatorResponse, VoiceoverResponse, TypedDict

### Community 4 - "Assembler_node Code_generator_node Post"
Cohesion: 0.43
Nodes (6): assembler_node(), code_generator_node(), _post(), script_writer_node(), validator_node(), voiceover_node()

### Community 5 - "Generate_espeak_fallback Generate_openai_tts Generate_voiceover"
Cohesion: 0.47
Nodes (5): generate_espeak_fallback(), generate_openai_tts(), generate_voiceover(), Generate TTS using OpenAI. Returns True if successful., Fallback to espeak (last resort).

### Community 6 - "Scene_4 Scene4 Construct"
Cohesion: 0.5
Nodes (1): Scene4

### Community 7 - "Basesettings Settings Config"
Cohesion: 0.67
Nodes (2): BaseSettings, Settings

### Community 8 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 9 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 10 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 11 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 12 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 13 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 14 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 15 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 16 - "Init__"
Cohesion: 1.0
Nodes (0): 

### Community 17 - "Init__"
Cohesion: 1.0
Nodes (0): 

## Knowledge Gaps
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Init__`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `health()` connect `Assemble_video Codegenoutput Generate_code` to `Generate_espeak_fallback Generate_openai_tts Generate_voiceover`?**
  _High betweenness centrality (0.108) - this node is a cross-community bridge._
- **Why does `CodeGenOutput` connect `Assemble_video Codegenoutput Generate_code` to `Basemodel Generationrequest Jobstate`, `Langgraphstate Scriptresponse Assemblerresponse`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `ScriptResponse` connect `Langgraphstate Scriptresponse Assemblerresponse` to `Basemodel Generationrequest Jobstate`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._
- **Are the 6 inferred relationships involving `ScriptResponse` (e.g. with `LangGraphState` and `ScriptWriterResponse`) actually correct?**
  _`ScriptResponse` has 6 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `ScenePlan` (e.g. with `ScriptWriterRequest` and `CodeGeneratorRequest`) actually correct?**
  _`ScenePlan` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `JobState` (e.g. with `ScriptWriterRequest` and `CodeGeneratorRequest`) actually correct?**
  _`JobState` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Should `Scene_1 Construct Scene_2` be split into smaller, more focused modules?**
  _Cohesion score 0.12 - nodes in this community are weakly interconnected._