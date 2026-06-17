import axios from "axios";

import { getApiBaseUrl } from "./api-base-url";
import { clearAuthToken, getAuthToken, setAuthToken } from "./auth";

export const API_BASE_URL = getApiBaseUrl();

if (!API_BASE_URL && process.env.NODE_ENV === "production") {
  console.error(
    "NEXT_PUBLIC_API_URL is missing. On Vercel, set a public HTTPS tunnel URL.",
  );
}

export const api = axios.create();

api.interceptors.request.use((config) => {
  config.baseURL = getApiBaseUrl();

  const token = getAuthToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  try {
    const host = new URL(config.baseURL).hostname;
    if (host.includes("ngrok")) {
      config.headers["ngrok-skip-browser-warning"] = "true";
    }
  } catch {
    /* ignore */
  }

  return config;
});

export type StudentProfile = {
  email: string;
  student_id?: string;
  name: string;
  face_registered: boolean;
  face_registered_at?: string | null;
  created_at?: string | null;
};

export type AttendanceStatus = {
  active: boolean;
  started_at: string | null;
  teacher_ip?: string | null;
  expected_classroom?: string | null;
  marked_count: number;
  marked_students: {
    email: string;
    name: string;
    marked_at: string;
    ip_match?: boolean;
    student_ip?: string | null;
    has_snapshot?: boolean;
    location?: string;
    location_confidence?: number;
    status?: string;
    reason?: string | null;
  }[];
};

export function attendanceSnapshotUrl(email: string): string {
  const base = getApiBaseUrl();
  return `${base}/attendance/snapshot/${encodeURIComponent(email)}`;
}

export async function registerStudent(
  name: string,
  images: {
    front: Blob;
    left: Blob;
    right: Blob;
  },
) {
  const formData = new FormData();
  formData.append("name", name.trim());
  formData.append("files", images.front, "front.jpg");
  formData.append("files", images.left, "left.jpg");
  formData.append("files", images.right, "right.jpg");

  const { data } = await api.post<{
    success: boolean;
    message: string;
    id?: string;
    student_id?: string;
    token?: string;
    student?: StudentProfile;
    scans_used?: number;
  }>("/register-student", formData);

  if (data.success && data.token) {
    setAuthToken(data.token);
  }

  return {
    ...data,
    id: data.id ?? data.student_id ?? data.student?.student_id,
  };
}

export async function loginWithFace(scan: Blob) {
  const formData = new FormData();
  formData.append("file", scan, "login.jpg");

  const { data } = await api.post<{
    success: boolean;
    message: string;
    token?: string;
    student?: StudentProfile;
    similarity?: number;
  }>("/auth/login", formData);

  if (data.success && data.token) {
    setAuthToken(data.token);
  }

  return data;
}

export function logout() {
  clearAuthToken();
}

export async function getMe() {
  const { data } = await api.get<{
    success: boolean;
    student: StudentProfile;
  }>("/auth/me");
  return data.student;
}

export async function listStudents() {
  const { data } = await api.get<{
    success: boolean;
    students: StudentProfile[];
  }>("/students");
  return data.students;
}

export async function startAttendance(classroom: string) {
  const { data } = await api.post<{
    success: boolean;
    message: string;
    started_at: string;
    classroom: string;
  }>("/attendance/start", { classroom });
  return data;
}

export async function stopAttendance() {
  const { data } = await api.post<{
    success: boolean;
    message: string;
    marked_count?: number;
    marked_students?: AttendanceStatus["marked_students"];
  }>("/attendance/stop");
  return data;
}

export async function getAttendanceStatus() {
  const { data } = await api.get<AttendanceStatus>("/attendance/status");
  return data;
}

export async function markAttendance(file: Blob | File) {
  const formData = new FormData();
  formData.append("file", file, "webcam.jpg");
  const { data } = await api.post<{
    success: boolean;
    verified?: boolean;
    message: string;
    similarity?: number;
    spoof_confidence?: number;
    marked_at?: string;
    student?: StudentProfile;
  }>("/students/me/mark-attendance", formData);
  return data;
}

export async function getStudentStatus() {
  const { data } = await api.get<{
    student_id: string;
    email: string;
    name: string;
    registered: boolean;
    attendance_active: boolean;
    already_marked: boolean;
  }>("/students/me/status");
  return data;
}
