/**
 * App.js — KisaanDost / FarmAI
 *
 * Stage 1: minimal health-check screen.
 * Displays the project title, a "Check Backend" button, and
 * the result (success in green, error in red, spinner while loading).
 */

import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { StatusBar } from "expo-status-bar";

import API_BASE_URL from "./src/config";
import { checkHealth } from "./src/services/api";

export default function App() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null); // { ok: bool, message: string }

  const handleCheck = async () => {
    setLoading(true);
    setResult(null);
    try {
      const data = await checkHealth();
      setResult({
        ok: true,
        message: `Backend OK (environment: ${data.environment})`,
      });
    } catch (err) {
      setResult({ ok: false, message: err.message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="dark" />

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>🌾 FarmAI</Text>
        <Text style={styles.subtitle}>AI Assistant for Pakistani Farmers</Text>
      </View>

      {/* Config warning */}
      {!API_BASE_URL && (
        <View style={styles.warning}>
          <Text style={styles.warningText}>
            ⚠️  Backend URL not configured.{"\n"}
            Copy <Text style={styles.code}>frontend/.env.example</Text> to{" "}
            <Text style={styles.code}>frontend/.env</Text> and set{" "}
            <Text style={styles.code}>EXPO_PUBLIC_API_URL</Text> to your PC's local IP.
          </Text>
        </View>
      )}

      {/* Button */}
      <Pressable
        style={({ pressed }) => [
          styles.button,
          pressed && styles.buttonPressed,
        ]}
        onPress={handleCheck}
        disabled={loading}
        accessibilityLabel="Check backend connectivity"
      >
        <Text style={styles.buttonText}>Check Backend</Text>
      </Pressable>

      {/* Loading */}
      {loading && (
        <ActivityIndicator
          size="large"
          color="#2e7d32"
          style={styles.spinner}
        />
      )}

      {/* Result */}
      {result && !loading && (
        <View
          style={[
            styles.resultBox,
            result.ok ? styles.resultOk : styles.resultError,
          ]}
        >
          <Text
            style={[
              styles.resultText,
              result.ok ? styles.resultTextOk : styles.resultTextError,
            ]}
          >
            {result.message}
          </Text>
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#f5f5f0",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
  header: {
    alignItems: "center",
    marginBottom: 40,
  },
  title: {
    fontSize: 42,
    fontWeight: "700",
    color: "#1b5e20",
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: "#555",
    textAlign: "center",
  },
  warning: {
    backgroundColor: "#fff8e1",
    borderColor: "#f9a825",
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    marginBottom: 28,
    width: "100%",
  },
  warningText: {
    color: "#6d4c00",
    fontSize: 13,
    lineHeight: 20,
  },
  code: {
    fontFamily: "monospace",
    backgroundColor: "#ffe082",
    paddingHorizontal: 3,
    borderRadius: 3,
  },
  button: {
    backgroundColor: "#2e7d32",
    paddingVertical: 14,
    paddingHorizontal: 36,
    borderRadius: 10,
    elevation: 2,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.15,
    shadowRadius: 4,
  },
  buttonPressed: {
    backgroundColor: "#1b5e20",
    transform: [{ scale: 0.97 }],
  },
  buttonText: {
    color: "#fff",
    fontSize: 17,
    fontWeight: "600",
    letterSpacing: 0.3,
  },
  spinner: {
    marginTop: 28,
  },
  resultBox: {
    marginTop: 24,
    padding: 16,
    borderRadius: 10,
    width: "100%",
    borderWidth: 1,
  },
  resultOk: {
    backgroundColor: "#e8f5e9",
    borderColor: "#a5d6a7",
  },
  resultError: {
    backgroundColor: "#ffebee",
    borderColor: "#ef9a9a",
  },
  resultText: {
    fontSize: 15,
    textAlign: "center",
    fontWeight: "500",
  },
  resultTextOk: {
    color: "#1b5e20",
  },
  resultTextError: {
    color: "#b71c1c",
  },
});
