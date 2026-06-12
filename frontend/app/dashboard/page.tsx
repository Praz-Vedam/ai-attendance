"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Webcam from "react-webcam";

import {
  getMe,
  getStudentStatus,
  logout,
  markAttendance,
  type StudentProfile,
} from "@/lib/api";
import { getAuthToken } from "@/lib/auth";
import { useFaceDetection } from "@/lib/useFaceDetection";

export default function DashboardPage() {
  const router = useRouter();
  const webcamRef = useRef<Webcam>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionActive, setSessionActive] = useState(false);
  const [alreadyMarked, setAlreadyMarked] = useState(false);
  const [cameraReady, setCameraReady] = useState(false);

  const faceDetectionState = useFaceDetection(videoRef, "attendance");

  const loadProfile = useCallback(async () => {
    if (!getAuthToken()) {
      router.replace("/login");
      return;
    }

    try {
      const [me, studentStatus] = await Promise.all([
        getMe(),
        getStudentStatus(),
      ]);
      setProfile(me);
      setSessionActive(studentStatus.attendance_active);
      setAlreadyMarked(studentStatus.already_marked);
    } catch {
      router.replace("/login");
    }
  }, [router]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  useEffect(() => {
    const interval = setInterval(loadProfile, 5000);
    return () => clearInterval(interval);
  }, [loadProfile]);

  const handleMarkAttendance = async () => {
    setLoading(true);
    setStatus("");

    try {
      const screenshot = webcamRef.current?.getScreenshot();
      if (!screenshot) {
        setStatus("Could not capture from webcam");
        setLoading(false);
        return;
      }

      const blob = await fetch(screenshot).then((res) => res.blob());
      const data = await markAttendance(blob);
      setStatus(data.message);
      if (data.success) {
        setAlreadyMarked(true);
      }
      await loadProfile();
    } catch {
      setStatus("Could not mark attendance");
    }

    setLoading(false);
  };

  const handleLogout = () => {
    logout();
    router.push("/login");
  };

  if (!profile) {
    return (
      <main className="min-h-screen bg-black text-white px-6 py-10">
        <p className="text-zinc-400">Loading…</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-3xl mx-auto space-y-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <Link href="/" className="text-zinc-400 hover:text-white text-sm">
              ← Home
            </Link>
            <h1 className="text-4xl font-bold mt-4 mb-2">Hi, {profile.name}</h1>
            <p className="text-green-400">Face enrolled</p>
          </div>
          <button
            type="button"
            onClick={handleLogout}
            className="text-zinc-400 hover:text-white text-sm"
          >
            Sign out
          </button>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 space-y-6">
          <h2 className="text-2xl font-semibold">Mark attendance</h2>

          {!sessionActive && (
            <p className="text-zinc-400">
              Waiting for your teacher to start the attendance session. This page
              will show the face scanner when the session opens.
            </p>
          )}

          {sessionActive && alreadyMarked && (
            <p className="text-green-400 font-medium">
              You have already marked attendance for this session.
            </p>
          )}

          {sessionActive && !alreadyMarked && (
            <>
              <p className="text-green-400">
                Attendance session is open — scan your face below
              </p>

              <div className="relative">
                <Webcam
                  ref={webcamRef}
                  screenshotFormat="image/jpeg"
                  className="rounded-3xl w-full border border-zinc-700 block"
                  videoConstraints={{
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    facingMode: "user",
                  }}
                  onUserMedia={() => {
                    if (webcamRef.current?.video) {
                      videoRef.current = webcamRef.current.video;
                      setCameraReady(true);
                    }
                  }}
                />
                {cameraReady && (
                  <svg
                    width="100%"
                    height="100%"
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      pointerEvents: "none",
                    }}
                    viewBox="0 0 1280 720"
                    preserveAspectRatio="none"
                  >
                    <defs>
                      <style>{`
                        .face-guide-oval {
                          fill: none;
                          stroke: ${
                            faceDetectionState.aligned ? "#22c55e" : "#ef4444"
                          };
                          stroke-width: 3;
                          opacity: 0.8;
                        }
                      `}</style>
                    </defs>
                    {/* Face oval guide */}
                    <ellipse
                      cx="640"
                      cy="320"
                      rx="160"
                      ry="220"
                      className="face-guide-oval"
                    />
                    {/* Shoulder guide */}
                    <path
                      d="M 300 500 Q 640 580 980 500 L 980 620 Q 640 650 300 620 Z"
                      fill="none"
                      stroke={
                        faceDetectionState.aligned ? "#22c55e" : "#ef4444"
                      }
                      strokeWidth="3"
                      opacity="0.8"
                    />
                    {/* Center crosshair */}
                    <g
                      stroke={
                        faceDetectionState.aligned ? "#22c55e" : "#ef4444"
                      }
                      strokeWidth="2"
                      opacity="0.4"
                    >
                      <line x1="600" y1="320" x2="680" y2="320" />
                      <line x1="640" y1="280" x2="640" y2="360" />
                    </g>
                  </svg>
                )}
              </div>

              {/* Face alignment status */}
              <div className="text-center py-4">
                {faceDetectionState.aligned ? (
                  <p className="text-green-400 font-semibold text-lg">
                    ✓ Face Aligned
                  </p>
                ) : (
                  <p className="text-red-400 font-semibold text-lg">
                    ⚠ {faceDetectionState.message}
                  </p>
                )}
              </div>

              <button
                type="button"
                onClick={handleMarkAttendance}
                disabled={loading || !faceDetectionState.aligned}
                className="bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition px-8 py-4 rounded-2xl font-semibold"
              >
                {loading
                  ? "Verifying…"
                  : "Mark attendance with face scan"}
              </button>
            </>
          )}
        </div>

        {status && (
          <div
            className={`w-fit px-8 py-5 rounded-2xl text-lg font-semibold border ${
              status.includes("success") || status.includes("marked")
                ? "bg-green-600/20 text-green-400 border-green-500"
                : "bg-zinc-800 text-zinc-200 border-zinc-600"
            }`}
          >
            {status}
          </div>
        )}
      </div>
    </main>
  );
}
