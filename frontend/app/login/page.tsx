"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Webcam from "react-webcam";

import { loginWithFace } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const webcamRef = useRef<Webcam>(null);

  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    setMessage("");

    try {
      const screenshot = webcamRef.current?.getScreenshot();
      if (!screenshot) {
        setMessage("Could not capture from webcam");
        setLoading(false);
        return;
      }

      const blob = await fetch(screenshot).then((res) => res.blob());
      const data = await loginWithFace(blob);

      if (!data.success) {
        setMessage(data.message);
        setLoading(false);
        return;
      }

      router.push("/dashboard");
    } catch {
      setMessage("Sign in failed. Is the backend running?");
    }

    setLoading(false);
  };

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-lg mx-auto space-y-8">
        <div>
          <Link href="/" className="text-zinc-400 hover:text-white text-sm">
            ← Home
          </Link>
          <h1 className="text-4xl font-bold mt-4 mb-2">Student sign in</h1>
          <p className="text-zinc-400">
            Look at the camera and sign in with your registered face. No password
            needed.
          </p>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 space-y-5">
          <Webcam
            ref={webcamRef}
            screenshotFormat="image/jpeg"
            className="rounded-3xl w-full border border-zinc-700"
          />

          <button
            type="button"
            onClick={handleLogin}
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 transition py-4 rounded-2xl font-semibold"
          >
            {loading ? "Recognizing…" : "Sign in with face scan"}
          </button>
        </div>

        <p className="text-zinc-500 text-sm text-center">
          New student?{" "}
          <Link
            href="/register-student"
            className="text-blue-400 hover:text-blue-300"
          >
            Register with name and face scans
          </Link>
        </p>

        {message && (
          <p className="text-red-400 text-center font-medium">{message}</p>
        )}
      </div>
    </main>
  );
}
