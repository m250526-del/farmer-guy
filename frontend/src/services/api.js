/**
 * src/services/api.js
 *
 * Thin API layer for the FarmAI backend.
 * Currently exposes:  checkHealth()
 * More functions will be added in later stages (analyzeText, voiceAnalyze …).
 */

import API_BASE_URL from "../config";

const TIMEOUT_MS = 10_000; // 10 seconds

/**
 * GET /health
 *
 * Verifies that the backend is reachable and running.
 * @returns {Promise<{status: string, project: string, environment: string}>}
 * @throws {Error} on network failure, timeout, or non-2xx response
 */
export async function checkHealth() {
  if (!API_BASE_URL) {
    throw new Error(
      "Backend URL is not configured. Copy frontend/.env.example to frontend/.env and set EXPO_PUBLIC_API_URL to your PC's local IP."
    );
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(
        `Backend returned HTTP ${response.status} ${response.statusText}`
      );
    }

    return await response.json();
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(
        `Request timed out after ${TIMEOUT_MS / 1000} seconds. Is the backend running and reachable?`
      );
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

