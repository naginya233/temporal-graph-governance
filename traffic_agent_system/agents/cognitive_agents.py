import requests
from typing import Dict, Any
from governance.graph_analyzer import TrafficGraphAnalyzer

class SceneAgent:
    """
    Scene Agent (场景理解智能体)
    Focuses on macro-level relations and aggregates subgraphs to recognize global patterns.
    """
    def __init__(self):
        self.name = "SceneAgent"

    def process(self, frame_id: str, scene_graph_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes raw scene graph output and performs structure analysis.
        """
        analyzer = TrafficGraphAnalyzer(scene_graph_dict)
        
        # 1. 挖掘让行失序
        yielding_issues = analyzer.identify_yielding_disorder()
        
        # 2. 挖掘拥堵传导链
        conflict_chains = analyzer.trace_conflict_propagation()
        
        # 3. 诊断跟驰网络健康度
        following_diagnostics = analyzer.diagnose_following_anomaly()
        
        # 4. 识别多边僵局
        deadlocks = analyzer.detect_multi_agent_deadlocks()
        
        return {
            "frame_id": frame_id,
            "yielding_disorders": yielding_issues,
            "conflict_propagation_chains": conflict_chains,
            "following_health": following_diagnostics,
            "game_deadlocks": deadlocks
        }

class EventAgent:
    """
    Event Agent (事件推理智能体)
    Uses LLM / Rule-based prompting over the macro structures detected by SceneAgent to issue governance insights.
    """
    def __init__(
        self,
        use_llm: bool = True,
        ollama_url: str = "http://localhost:11434/api/generate",
        model_name: str = "qwen3-vl:4b",
        request_timeout: int = 20,
    ):
        self.name = "EventAgent"
        self.use_llm = use_llm
        self.ollama_url = ollama_url
        self.model_name = model_name
        self.request_timeout = request_timeout

    def _score_risk(self, scene_insights: Dict[str, Any]) -> Dict[str, Any]:
        yielding_cnt = len(scene_insights.get("yielding_disorders", []))
        chain_cnt = len(scene_insights.get("conflict_propagation_chains", []))
        deadlock_cnt = len(scene_insights.get("game_deadlocks", []))
        following = scene_insights.get("following_health", {})
        bottleneck_cnt = len(following.get("structural_bottlenecks", []))
        cycle_detected = bool(following.get("cycle_detected", False))
        max_chain = int(following.get("max_following_chain", 0))

        score = 0
        score += min(yielding_cnt, 3) * 3
        score += min(chain_cnt, 3) * 2
        score += min(deadlock_cnt, 2) * 4
        score += 2 if cycle_detected else 0
        score += 1 if max_chain >= 4 else 0
        score += 1 if bottleneck_cnt >= 2 else 0

        if score >= 8:
            level = "high"
        elif score >= 4:
            level = "medium"
        else:
            level = "low"

        return {
            "score": score,
            "level": level,
            "yielding_cnt": yielding_cnt,
            "chain_cnt": chain_cnt,
            "deadlock_cnt": deadlock_cnt,
            "bottleneck_cnt": bottleneck_cnt,
            "cycle_detected": cycle_detected,
            "max_chain": max_chain,
        }
        
    def _generate_prompt(self, scene_insights: Dict[str, Any], risk: Dict[str, Any]) -> str:
        prompt = f"### 交叉口系统认知报告 (Frame {scene_insights['frame_id']}) ###\n"
        prompt += f"- 风险等级: {risk['level']} (score={risk['score']})\n"
        
        yd = scene_insights['yielding_disorders']
        if yd:
            prompt += f"- [危] 发现 {len(yd)} 处让行失序: 实体间存在冲突但无明确让行关系 (如 {yd[0]})\n"
            
        cc = scene_insights['conflict_propagation_chains']
        if cc:
            prompt += f"- [警] 发现次生拥堵传播链: {' -> '.join(cc[0])} 发挥级联阻塞效应\n"
            
        fh = scene_insights['following_health']
        if fh.get('max_following_chain', 0) >= 3:
            prompt += f"- [诊] 编队严重缓行: 发现长度达 {fh['max_following_chain']} 的跟驰链\n"
        if fh.get('structural_bottlenecks'):
            prompt += f"- [源] 跟驰拓扑瓶颈定位: 实体 {fh['structural_bottlenecks']} 成为车流拥堵头节点\n"
            
        dl = scene_insights['game_deadlocks']
        if dl:
            prompt += f"- [锁] 发生多主体博弈死锁: 实体环 {dl[0]} 产生相互等待关系\n"
            
        if not (yd or cc or (fh.get('max_following_chain', 0) >= 3) or fh.get('structural_bottlenecks') or dl):
            prompt += "- [稳] 路权博弈暂态平衡，无严重关系拓扑异常\n"
            
        return prompt

    @staticmethod
    def _should_call_llm(risk: Dict[str, Any]) -> bool:
        return risk["level"] in {"medium", "high"}

    def _call_ollama(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model_name,
            "prompt": f"{system_prompt}\n\n当前路口状态:\n{user_prompt}\n\n请给出治理建议：",
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }
        try:
            response = requests.post(self.ollama_url, json=payload, timeout=self.request_timeout)
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "").strip()
            return f"[LLM 异常] 状态码: {response.status_code}"
        except requests.exceptions.RequestException as exc:
            return f"[LLM 服务未响应] {exc}"

    def reason(self, scene_insights: Dict[str, Any]) -> str:
        analysis = self.analyze(scene_insights)
        return analysis["report"]

    def analyze(self, scene_insights: Dict[str, Any]) -> Dict[str, Any]:
        risk = self._score_risk(scene_insights)
        prompt = self._generate_prompt(scene_insights, risk)
        
        fast_decision = (
            "【快速决策】触发视觉重采样与关系复核。"
            if risk["level"] in {"medium", "high"}
            else "【快速决策】维持当前轻量化监控。"
        )
        
        llm_insight = ""
        if self.use_llm and self._should_call_llm(risk):
            sys_prompt = (
                "你是交通治理分析助手。"
                "请基于结构化结果给出原因判断和两条可执行建议，"
                "并明确是否需要触发视觉重采样。"
                "回答控制在3句话内。"
            )
            llm_reply = self._call_ollama(sys_prompt, prompt)
            llm_insight = f"\n【大模型(Qwen3-VL)深度语义推理】\n{llm_reply}"

        report = prompt + fast_decision + llm_insight
        return {
            "risk": risk,
            "fast_decision": fast_decision,
            "llm_insight": llm_insight,
            "report": report,
        }
