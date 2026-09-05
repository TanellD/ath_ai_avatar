/**
 * База знаний сценария — зеркало packages/contracts/ath_contracts/knowledge.py.
 * Обслуживается rag-service (issue #11), не gateway и не scenario-service.
 */

export interface KnowledgeDocInfo {
  filename: string;
  chunk_count: number;
  uploaded_at: string;
}
