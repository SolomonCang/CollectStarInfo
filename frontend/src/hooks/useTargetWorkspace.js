import { useCallback, useEffect, useRef, useState } from "react";
import { listLlmProfiles, queryTarget, researchLiterature } from "../api";

export function useTargetWorkspace() {
  const [targetName, setTargetName] = useState("AD Leo");
  const [useLlm, setUseLlm] = useState(false);
  const [forceRefresh, setForceRefresh] = useState(false);
  const [targetResult, setTargetResult] = useState(null);
  const [targetBusy, setTargetBusy] = useState(false);
  const [literatureQuestion, setLiteratureQuestion] = useState(
    "重点关注光变曲线、周期、恒星活动和磁场相关研究。"
  );
  const [literatureReport, setLiteratureReport] = useState(null);
  const [literatureBusy, setLiteratureBusy] = useState(false);
  const [prescreenKeywords, setPrescreenKeywords] = useState(true);
  const [llmProfiles, setLlmProfiles] = useState([]);
  const [llmProfileId, setLlmProfileId] = useState("");
  const [error, setError] = useState("");
  const queryControllerRef = useRef(null);

  useEffect(() => () => queryControllerRef.current?.abort(), []);

  useEffect(() => {
    listLlmProfiles().then((result) => {
      const profiles = result.profiles || [];
      setLlmProfiles(profiles);
      setLlmProfileId((current) => current || profiles.find((profile) => profile.is_default)?.id || profiles[0]?.id || "");
    }).catch(() => {});
  }, []);

  const handleTargetQuery = useCallback(async (event) => {
    event?.preventDefault();
    queryControllerRef.current?.abort();
    const controller = new AbortController();
    queryControllerRef.current = controller;
    setError("");
    setTargetBusy(true);

    try {
      const result = await queryTarget({
        target: targetName,
        use_llm: useLlm,
        force_refresh: forceRefresh,
        llm_profile_id: llmProfileId || null,
      }, { signal: controller.signal });
      setTargetResult(result);
      setLiteratureReport(null);
      if (result.llm_error) setError(result.llm_error);
    } catch (caught) {
      if (caught.name !== "AbortError") setError(caught.message);
    } finally {
      if (queryControllerRef.current === controller) {
        queryControllerRef.current = null;
        setTargetBusy(false);
      }
    }
  }, [targetName, useLlm, forceRefresh, llmProfileId]);

  const handleLiteratureResearch = useCallback(async () => {
    const target = targetResult?.target;
    if (!target) return;
    setError("");
    setLiteratureBusy(true);
    try {
      const response = await researchLiterature({
        target: target.resolved_target || target.query_target || targetName,
        target_type: target.target_type || "unknown",
        references: target.literature_references?.length
          ? target.literature_references
          : target.simbad?.references ?? [],
        literature_workflow: target.literature_workflow ?? null,
        focus_question: literatureQuestion,
        prescreen_keywords: prescreenKeywords,
        llm_profile_id: llmProfileId || null,
      });
      setLiteratureReport(response);
    } catch (caught) {
      setError(caught.message);
    } finally {
      setLiteratureBusy(false);
    }
  }, [targetResult, targetName, literatureQuestion, prescreenKeywords, llmProfileId]);

  const targetReferences = targetResult?.target?.literature_references;
  const references = targetReferences?.length
    ? targetReferences
    : (targetResult?.target?.simbad?.references ?? []);

  return {
    error,
    forceRefresh,
    handleLiteratureResearch,
    handleTargetQuery,
    literatureBusy,
    literatureQuestion,
    literatureReport,
    llmProfileId,
    llmProfiles,
    prescreenKeywords,
    references,
    setForceRefresh,
    setLiteratureQuestion,
    setLlmProfileId,
    setPrescreenKeywords,
    setTargetName,
    setUseLlm,
    targetBusy,
    targetName,
    targetResult,
    useLlm,
  };
}
