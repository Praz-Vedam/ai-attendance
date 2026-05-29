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

export default function DashboardPage() {
  const router = useRouter();
  const webcamRef = useRef<Webcam>(null);

  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionActive, setSessionActive] = useState(false);
  const [alreadyMarked, setAlreadyMarked] = useState(false);

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
          <p
            className={sessionActive ? "text-green-400" : "text-zinc-400"}
          >
            {sessionActive
              ? "Attendance session is open — scan your face below"
              : "Waiting for teacher to start attendance"}
          </p>

          <Webcam
            ref={webcamRef}
            screenshotFormat="image/jpeg"
            className="rounded-3xl w-full border border-zinc-700"
          />

          <button
            type="button"
            onClick={handleMarkAttendance}
            disabled={loading || !sessionActive || alreadyMarked}
            className="bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition px-8 py-4 rounded-2xl font-semibold"
          >
            {alreadyMarked
              ? "Already marked this session"
              : loading
                ? "Verifying…"
                : "Mark attendance with face scan"}
          </button>
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
