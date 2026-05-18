"""
v2_engine.agents.langgraph_dag — alternative MAS wiring via LangGraph.

Optional. Use when you want a stateful, branching agent DAG instead of
the linear Generator pipeline. Activated by passing
``use_langgraph=True`` to the orchestrator constructor (TODO).
"""
from __future__ import annotations


def build_graph(generation: int = 0):
    """Return a compiled LangGraph StateGraph for the V2 trading day.

    Nodes: eda -> planner? -> extractor -> qa? -> quant -> synthesizer -> persona
    Branch: planner+qa only if EDA detects an anomaly.
    """
    try:
        from langgraph.graph import StateGraph, END
    except Exception as e:
        raise RuntimeError(f"langgraph not installed: {e}")

    from v2_engine.agents.eda import EnterpriseDiscoveryAgent
    from v2_engine.agents.planner import Planner
    from v2_engine.agents.extractor import Extractor
    from v2_engine.agents.qa import QA
    from v2_engine.agents.quant import Quant
    from v2_engine.agents.synthesizer import Synthesizer
    from v2_engine.agents.persona import Persona
    from v2_engine.agents.base import AgentContext

    eda = EnterpriseDiscoveryAgent()
    planner, extractor, qa = Planner(), Extractor(), QA()
    quant = Quant(generation=generation)
    synth, persona = Synthesizer(), Persona()

    def n_eda(state):
        from shared.ledger_schema import Ledger
        state["constraints"] = eda.probe(state.get("ledger") or Ledger())
        return state

    def n_planner(state):
        ctx = AgentContext(trading_day=state["trading_day"], constraints=state["constraints"])
        state["plan"] = planner.run(ctx)
        return state

    def n_extractor(state):
        ctx = AgentContext(trading_day=state["trading_day"],
                           constraints=state["constraints"],
                           prior_outputs={"plan": state.get("plan", {})})
        state["retrieval"] = extractor.run(ctx)
        return state

    def n_qa(state):
        ctx = AgentContext(trading_day=state["trading_day"],
                           constraints=state["constraints"],
                           retrieval=state["retrieval"])
        state["retrieval"] = qa.run(ctx)
        return state

    def n_quant(state):
        ctx = AgentContext(trading_day=state["trading_day"],
                           constraints=state["constraints"],
                           retrieval=state["retrieval"])
        state["candidates"] = quant.run(ctx)
        return state

    def n_synth(state):
        state["candidates"] = synth.apply_constraints(state["candidates"], state["constraints"])
        return state

    def n_persona(state):
        for c in state["candidates"][:3]:
            c.thesis = persona.translate(c.thesis)
        return state

    def route_after_eda(state):
        return "planner" if state["constraints"].get("anomaly_detected") else "extractor"

    g = StateGraph(dict)
    g.add_node("eda", n_eda)
    g.add_node("planner", n_planner)
    g.add_node("extractor", n_extractor)
    g.add_node("qa", n_qa)
    g.add_node("quant", n_quant)
    g.add_node("synth", n_synth)
    g.add_node("persona", n_persona)
    g.set_entry_point("eda")
    g.add_conditional_edges("eda", route_after_eda,
                            {"planner": "planner", "extractor": "extractor"})
    g.add_edge("planner", "extractor")
    g.add_edge("extractor", "qa")
    g.add_edge("qa", "quant")
    g.add_edge("quant", "synth")
    g.add_edge("synth", "persona")
    g.add_edge("persona", END)
    return g.compile()
