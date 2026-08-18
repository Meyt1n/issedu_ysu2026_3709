const MAX_SUGGESTIONS = 3
const MAX_QUESTION_LENGTH = 80

/**
 * Defensive client-side normalization for the optional API field.
 * Suggestions are prompts only; the server remains responsible for safety.
 */
export function normalizeSuggestedQuestions(value: unknown): string[] {
  if (!Array.isArray(value)) return []

  const result: string[] = []
  const seen = new Set<string>()
  for (const item of value) {
    if (typeof item !== 'string') continue
    const question = item.trim().replace(/\s+/g, ' ')
    const key = question.toLocaleLowerCase()
    if (!question || question.length > MAX_QUESTION_LENGTH || seen.has(key)) continue
    seen.add(key)
    result.push(question)
    if (result.length >= MAX_SUGGESTIONS) break
  }
  return result
}
