"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Webcam from "react-webcam";

import { registerStudent } from "@/lib/api";

const REQUIRED_SCANS = 3;

export default function RegisterStudentPage() {
  const router = useRouter();
  const webcamRef = useRef<Webcam>(null);

  const [name, setName] = useState("");
  const [scans, setScans] = useState<Blob[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [registeredId, setRegisteredId] = useState<string | null>(null);

  const captureScan = async () => {
    const screenshot = webcamRef.current?.getScreenshot();
    if (!screenshot) {
      setMessage("Could not capture from webcam");
      return;
    }

    const blob = await fetch(screenshot).then((res) => res.blob());
    setScans((prev) => [...prev, blob].slice(0, REQUIRED_SCANS));
    setMessage("");
  };

  const handleRegister = async () => {
    if (!name.trim()) {
      setMessage("Enter your name");
      return;
    }

    if (scans.length < REQUIRED_SCANS) {
      setMessage(
        `Capture ${REQUIRED_SCANS} face scans (${scans.length}/${REQUIRED_SCANS})`
      );
      return;
    }

    setLoading(true);
    setMessage("");
    setRegisteredId(null);

    try {
      const data = await registerStudent(name, scans);
      if (!data.success || !data.id) {
        setMessage(data.message);
        setLoading(false);
        return;
      }

      setRegisteredId(data.id);
      setMessage(data.message);
    } catch {
      setMessage("Registration failed. Is the backend running?");
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
          <h1 className="text-4xl font-bold mt-4 mb-2">Register student</h1>
          <p className="text-zinc-400">
            Enter your name and capture {REQUIRED_SCANS} face scans. You will
            receive a student ID when registration succeeds.
          </p>
        </div>

        {registeredId ? (
          <div className="bg-zinc-900 border border-green-500/50 rounded-3xl p-8 space-y-6">
            <p className="text-green-400 font-semibold text-lg">
              Registration successful
            </p>
            <div>
              <p className="text-zinc-400 text-sm mb-2">Your student ID</p>
              <p className="font-mono text-xl break-all bg-zinc-800 px-4 py-3 rounded-xl">
                {registeredId}
              </p>
              <p className="text-zinc-500 text-sm mt-3">
                Save this ID. Teachers can use it to find you on the roster.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => router.push("/dashboard")}
                className="bg-blue-600 hover:bg-blue-500 transition px-6 py-3 rounded-2xl font-semibold"
              >
                Go to dashboard
              </button>
              <button
                type="button"
                onClick={() => router.push("/login")}
                className="bg-zinc-700 hover:bg-zinc-600 transition px-6 py-3 rounded-2xl font-semibold"
              >
                Sign in later
              </button>
            </div>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 space-y-5">
            <div>
              <label className="block text-sm text-zinc-400 mb-2">
                Your name
              </label>
              <input
                type="text"
                required
                placeholder="Full name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-2xl px-5 py-4 outline-none"
              />
            </div>

            <Webcam
              ref={webcamRef}
              screenshotFormat="image/jpeg"
              className="rounded-3xl w-full border border-zinc-700"
            />

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={captureScan}
                disabled={loading || scans.length >= REQUIRED_SCANS}
                className="bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 transition px-6 py-3 rounded-2xl font-semibold"
              >
                Capture scan ({scans.length}/{REQUIRED_SCANS})
              </button>
              <button
                type="button"
                onClick={() => setScans([])}
                disabled={loading || scans.length === 0}
                className="text-zinc-400 hover:text-white text-sm px-2"
              >
                Clear scans
              </button>
            </div>

            {scans.length > 0 && (
              <p className="text-green-400 text-sm">
                {scans.length} scan{scans.length === 1 ? "" : "s"} ready
              </p>
            )}

            <button
              type="button"
              onClick={handleRegister}
              disabled={loading || scans.length < REQUIRED_SCANS}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition py-4 rounded-2xl font-semibold"
            >
              {loading ? "Registering…" : "Register student"}
            </button>
          </div>
        )}

        {!registeredId && (
          <p className="text-zinc-500 text-sm text-center">
            Already enrolled?{" "}
            <Link href="/login" className="text-blue-400 hover:text-blue-300">
              Sign in with your face
            </Link>
          </p>
        )}

        {message && !registeredId && (
          <p className="text-red-400 text-center font-medium">{message}</p>
        )}
      </div>
    </main>
  );
}
