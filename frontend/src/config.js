/**
 * src/config.js
 *
 * Reads the backend URL from the Expo public environment variable.
 * If the variable is missing or still contains the placeholder text,
 * API_BASE_URL is set to null so the app can show a helpful message
 * instead of crashing on a bad fetch.
 */

const raw = process.env.EXPO_PUBLIC_API_URL;

const isPlaceholder =
  !raw ||
  raw.trim() === "" ||
  raw.includes("YOUR_PC_IP");

/**
 * Base URL for all API calls.
 * null when the variable is unset or still contains the placeholder.
 */
const API_BASE_URL = isPlaceholder ? null : raw.trim().replace(/\/$/, "");

export default API_BASE_URL;

