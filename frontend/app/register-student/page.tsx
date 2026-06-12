"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import Webcam from "react-webcam";

import { registerStudent } from "@/lib/api";
import { useFaceDetection } from "@/lib/useFaceDetection";

const REQUIRED_SCANS = 3;
const HOLD_DURATION_MS = 1000;
const GUIDE_GREEN = "#22c55e";
const GUIDE_RED = "#ef4444";

const SCANS = [
  {
    key: "front",
    instruction: "Look straight at the camera",
    captured: "Front Face Captured",
    yawMin: -10,
    yawMax: 10,
    poseMessage: "Look straight at the camera",
  },
  {
    key: "left",
    instruction: "Turn your head slightly left",
    captured: "Left Profile Captured",
    yawMin: -20,
    yawMax: -15,
    poseMessage: "Turn your head slightly left",
  },
  {
    key: "right",
    instruction: "Turn your head slightly right",
    captured: "Right Profile Captured",
    yawMin: 15,
    yawMax: 20,
    poseMessage: "Turn your head slightly right",
  },
] as const;

export default function RegisterStudentPage() {
  const router = useRouter();
  const webcamRef = useRef<Webcam>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);

  const [name, setName] = useState("");
  const [scans, setScans] = useState<Blob[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [registeredId, setRegisteredId] = useState<string | null>(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [currentScan, setCurrentScan] = useState(0);
  const [captureMessage, setCaptureMessage] = useState("");
  const [countdownRunning, setCountdownRunning] = useState(false);

  const faceDetectionState = useFaceDetection(videoRef, "register");
  const captureInProgressRef = useRef(false);
  const holdTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const currentScanConfig = SCANS[Math.min(currentScan, REQUIRED_SCANS - 1)];
  const frontScanWidthRef = useRef<number | null>(null);
  const scansComplete = scans.length >= REQUIRED_SCANS;
  const faceAligned = faceDetectionState.aligned;
  const fullFaceVisible = faceDetectionState.isFullyVisible;

  const faceCenterX = faceDetectionState.faceCenterX;
  const videoCenterX = 320; // half of 640 webcam width

  let requiredPoseMatched = false;

  if (currentScan === 0) {

    requiredPoseMatched =

      faceCenterX !== null &&

      Math.abs(faceCenterX - videoCenterX) < 40;

  }

  if (currentScan === 1) {

    requiredPoseMatched =

      faceCenterX !== null &&

      faceCenterX < 335;

  }

  if (currentScan === 2) {

    requiredPoseMatched =

      faceCenterX !== null &&

      faceCenterX > 345;

  }
  const faceWidth = faceDetectionState.faceWidth;





  const poseValid = requiredPoseMatched;
  const canCapture =
    faceAligned && poseValid && fullFaceVisible && requiredPoseMatched;
  const alignmentMessage =
    currentScan === 0
      ? "Look straight at the camera"
      : currentScan === 1
        ? "Move face slightly left"
        : "Move face slightly right";

  const captureScan = useCallback(async () => {
    if (captureInProgressRef.current || scansComplete) return;

    const scanIndex = currentScan;
    captureInProgressRef.current = true;
    const screenshot = webcamRef.current?.getScreenshot();
    if (!screenshot) {
      setMessage("Could not capture from webcam");
      captureInProgressRef.current = false;
      return;
    }

    const blob = await fetch(screenshot).then((res) => res.blob());
    if (
      scanIndex === 0 &&
      faceDetectionState.faceWidth
    ) {
      frontScanWidthRef.current =
        faceDetectionState.faceWidth;
    }
    setScans((prev) => {
      if (prev.length !== scanIndex || prev.length >= REQUIRED_SCANS) {
        return prev;
      }

      return [...prev, blob];
    });
    setCaptureMessage(`✓ ${SCANS[scanIndex].captured}`);
    setCountdownRunning(false);
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }
    captureInProgressRef.current = false;
    setCurrentScan((prev) => Math.min(prev + 1, REQUIRED_SCANS));
    setMessage("");
  }, [currentScan, scansComplete]);

  useEffect(() => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }

    captureInProgressRef.current = false;
    setCountdownRunning(false);
  }, [currentScan]);

  useEffect(() => {
    console.log({
      currentScan,
      faceCenterX,
      poseValid,
      canCapture,
      failureReason: faceDetectionState.failureReason,
    });
  }, [
    canCapture,
    currentScan,
    faceAligned,
    poseValid,
    faceCenterX,
    faceWidth,
  ]);

  useEffect(() => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }

    if (
      loading ||
      scansComplete ||
      captureInProgressRef.current ||
      !canCapture ||
      scans.length !== currentScan
    ) {
      setCountdownRunning(false);
      return;
    }

    setCountdownRunning(true);
    holdTimerRef.current = setTimeout(() => {
      setCountdownRunning(false);
      void captureScan();
    }, HOLD_DURATION_MS);

    return () => {
      if (holdTimerRef.current) {
        clearTimeout(holdTimerRef.current);
        holdTimerRef.current = null;
      }
      setCountdownRunning(false);
    };
  }, [
    captureScan,
    canCapture,
    currentScan,
    loading,
    scans.length,
    scansComplete,
  ]);

  const handleRegister = async () => {
    if (!name.trim()) {
      setMessage("Enter your name");
      return;
    }

    if (!scansComplete) {
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

  const resetScans = () => {
    if (holdTimerRef.current) {
      clearTimeout(holdTimerRef.current);
      holdTimerRef.current = null;
    }

    setScans([]);
    setCurrentScan(0);
    setCaptureMessage("");
    setCountdownRunning(false);
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
            Enter your name and complete the guided face scans. You will receive
            a student ID when registration succeeds.
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

            <div className="text-center">
              <p className="text-zinc-400 text-sm mb-1">
                Scan {Math.min(scans.length + 1, REQUIRED_SCANS)}/{REQUIRED_SCANS}
              </p>
              <p className="text-xl font-semibold">
                {scansComplete
                  ? "Registration Scans Complete"
                  : currentScanConfig.instruction}
              </p>
            </div>

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
                        stroke: ${canCapture ? GUIDE_GREEN : GUIDE_RED
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
                      canCapture ? GUIDE_GREEN : GUIDE_RED
                    }
                    strokeWidth="3"
                    opacity="0.8"
                  />
                  {/* Center crosshair */}
                  <g
                    stroke={
                      canCapture ? GUIDE_GREEN : GUIDE_RED
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
              {scansComplete ? (
                <p className="text-green-400 font-semibold text-lg">
                  ✓ Registration Scans Complete
                </p>
              ) : canCapture ? (
                <p className="text-green-400 font-semibold text-lg">
                  ✓ Face Aligned
                  {countdownRunning ? " - Hold steady" : ""}
                </p>
              ) : (
                <p className="text-yellow-400 font-semibold text-lg">
                  ⚠ {alignmentMessage}
                </p>
              )}
              {captureMessage && (
                <p className="text-green-400 text-sm mt-2">{captureMessage}</p>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={resetScans}
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
              disabled={loading || !scansComplete}
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
