"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

type CameraStatus = "idle" | "requesting" | "granted" | "denied" | "unsupported";

export default function Home() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [cameraStatus, setCameraStatus] = useState<CameraStatus>("idle");

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
  }, []);

  const requestCamera = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraStatus("unsupported");
      return;
    }

    setCameraStatus("requesting");
    stopStream();

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user" },
      });
      streamRef.current = stream;
      setCameraStatus("granted");
    } catch {
      setCameraStatus("denied");
    }
  }, [stopStream]);

  useEffect(() => {
    void requestCamera();
    return () => stopStream();
  }, [requestCamera, stopStream]);

  useEffect(() => {
    if (cameraStatus !== "granted" || !streamRef.current || !videoRef.current) {
      return;
    }
    videoRef.current.srcObject = streamRef.current;
    void videoRef.current.play();
  }, [cameraStatus]);

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-3xl mx-auto space-y-10">
        <div>
          <h1 className="text-5xl font-bold mb-3">AI Attendance</h1>
          <p className="text-zinc-400 text-lg">
            Students sign up with their name and face scans only. Teachers
            manage sessions and see who is registered and present.
          </p>
        </div>

        <section className="bg-zinc-900 border border-zinc-800 rounded-3xl p-6 space-y-4">
          <h2 className="text-lg font-semibold">Camera access</h2>
          <p className="text-zinc-400 text-sm">
            Face registration and sign-in use your webcam. Allow camera access
            when your browser prompts you so those steps work smoothly.
          </p>

          {cameraStatus === "requesting" && (
            <p className="text-zinc-400 text-sm">Waiting for camera permission…</p>
          )}

          {cameraStatus === "granted" && (
            <div className="space-y-3">
              <p className="text-green-400 text-sm font-medium">Camera enabled</p>
              <video
                ref={videoRef}
                autoPlay
                playsInline
                muted
                className="rounded-2xl w-full max-w-sm border border-zinc-700 aspect-video object-cover"
              />
            </div>
          )}

          {cameraStatus === "denied" && (
            <div className="space-y-3">
              <p className="text-amber-400 text-sm">
                Camera access was blocked. Enable it in your browser settings,
                then try again.
              </p>
              <button
                type="button"
                onClick={() => void requestCamera()}
                className="bg-zinc-800 hover:bg-zinc-700 transition px-5 py-2.5 rounded-xl text-sm font-medium border border-zinc-700"
              >
                Allow camera
              </button>
            </div>
          )}

          {cameraStatus === "unsupported" && (
            <p className="text-red-400 text-sm">
              This browser does not support camera access. Try Chrome, Firefox,
              or Safari on a device with a webcam.
            </p>
          )}
        </section>

        <div className="grid gap-4 sm:grid-cols-2">
          <Link
            href="/register-student"
            className="bg-blue-600 hover:bg-blue-500 transition rounded-3xl p-8 font-semibold text-lg"
          >
            Register student
          </Link>
          <Link
            href="/login"
            className="bg-zinc-800 hover:bg-zinc-700 transition rounded-3xl p-8 font-semibold text-lg border border-zinc-700"
          >
            Student — sign in
          </Link>
          <Link
            href="/admin"
            className="sm:col-span-2 bg-zinc-900 hover:bg-zinc-800 transition rounded-3xl p-8 font-semibold text-lg border border-zinc-800 text-center"
          >
            Teacher / admin dashboard
          </Link>
        </div>

        <p className="text-zinc-500 text-sm">
          Sign up once with your name and three face scans. Later, sign in and
          mark attendance with a single face scan when the teacher opens the
          session.
        </p>
      </div>
    </main>
  );
}
