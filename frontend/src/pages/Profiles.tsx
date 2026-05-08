import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getProfiles, createProfile, updateProfile, deleteProfile,
  type Profile, type ProfileInput,
} from "../api/profiles";

const PRESET_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#ef4444",
  "#f97316", "#eab308", "#22c55e", "#14b8a6",
  "#3b82f6", "#64748b",
];

function ColorPicker({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return (
    <div className="flex gap-2 flex-wrap">
      {PRESET_COLORS.map(c => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={`w-7 h-7 rounded-full border-2 transition-transform ${
            value === c ? "border-white scale-110" : "border-transparent hover:scale-105"
          }`}
          style={{ background: c }}
        />
      ))}
      <input
        type="color"
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-7 h-7 rounded-full cursor-pointer border-2 border-zinc-600 bg-transparent"
        title="Свой цвет"
      />
    </div>
  );
}

interface ProfileFormData {
  name: string;
  description: string;
  color: string;
  avatar_url: string;
}

const emptyForm = (): ProfileFormData => ({
  name: "", description: "", color: "#6366f1", avatar_url: "",
});

function ProfileCard({
  profile,
  onEdit,
  onDelete,
}: {
  profile: Profile;
  onEdit: (p: Profile) => void;
  onDelete: (p: Profile) => void;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex items-start gap-4">
      {/* Avatar / color dot */}
      <div
        className="w-12 h-12 rounded-full shrink-0 flex items-center justify-center text-white font-bold text-lg border-2"
        style={{ background: profile.color, borderColor: profile.color }}
      >
        {profile.avatar_url ? (
          <img src={profile.avatar_url} alt="" className="w-full h-full object-cover rounded-full"
            onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none"; }} />
        ) : (
          profile.name.charAt(0).toUpperCase()
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="font-semibold text-white">{profile.name}</h3>
            <p className="text-xs text-zinc-500 mt-0.5">
              {profile.account_count} {profile.account_count === 1 ? "аккаунт" : profile.account_count < 5 ? "аккаунта" : "аккаунтов"}
            </p>
          </div>
          <div className="flex gap-1 shrink-0">
            <button
              onClick={() => onEdit(profile)}
              className="text-zinc-500 hover:text-white px-2 py-1 rounded-lg hover:bg-zinc-800 transition-colors text-sm"
            >
              Изменить
            </button>
            <button
              onClick={() => onDelete(profile)}
              className="text-zinc-600 hover:text-red-400 px-2 py-1 rounded-lg hover:bg-zinc-800 transition-colors text-sm"
            >
              Удалить
            </button>
          </div>
        </div>
        {profile.description && (
          <p className="text-sm text-zinc-400 mt-1 line-clamp-2">{profile.description}</p>
        )}
      </div>
    </div>
  );
}

function ProfileForm({
  initial,
  onSave,
  onCancel,
  loading,
}: {
  initial: ProfileFormData;
  onSave: (data: ProfileInput) => void;
  onCancel: () => void;
  loading: boolean;
}) {
  const [form, setForm] = useState<ProfileFormData>(initial);
  const set = (k: keyof ProfileFormData) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-5 space-y-4">
      {/* Name */}
      <div>
        <label className="block text-sm text-zinc-400 mb-1">Название *</label>
        <input
          value={form.name}
          onChange={e => set("name")(e.target.value)}
          placeholder="Название профиля"
          autoFocus
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
        />
      </div>

      {/* Description */}
      <div>
        <label className="block text-sm text-zinc-400 mb-1">Описание</label>
        <textarea
          value={form.description}
          onChange={e => set("description")(e.target.value)}
          placeholder="Кто это или что это за профиль"
          rows={2}
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500 resize-none"
        />
      </div>

      {/* Color */}
      <div>
        <label className="block text-sm text-zinc-400 mb-2">Цвет</label>
        <ColorPicker value={form.color} onChange={set("color")} />
      </div>

      {/* Avatar URL */}
      <div>
        <label className="block text-sm text-zinc-400 mb-1">Аватар (URL)</label>
        <input
          value={form.avatar_url}
          onChange={e => set("avatar_url")(e.target.value)}
          placeholder="https://..."
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-500"
        />
      </div>

      <div className="flex gap-2 pt-1">
        <button
          onClick={() => onSave(form)}
          disabled={!form.name.trim() || loading}
          className="bg-white text-black font-semibold px-5 py-2 rounded-lg text-sm disabled:opacity-40 hover:bg-zinc-100 transition-colors"
        >
          {loading ? "Сохраняю..." : "Сохранить"}
        </button>
        <button
          onClick={onCancel}
          className="text-zinc-400 hover:text-white px-4 py-2 rounded-lg text-sm transition-colors"
        >
          Отмена
        </button>
      </div>
    </div>
  );
}

function DeleteDialog({
  profile,
  onConfirm,
  onCancel,
}: {
  profile: Profile;
  onConfirm: (deleteAccounts: boolean) => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm px-4">
      <div className="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-full max-w-sm space-y-4">
        <h3 className="font-semibold text-white text-lg">Удалить профиль «{profile.name}»?</h3>
        <p className="text-zinc-400 text-sm">
          К профилю привязано <strong className="text-white">{profile.account_count}</strong>{" "}
          {profile.account_count === 1 ? "аккаунт" : profile.account_count < 5 ? "аккаунта" : "аккаунтов"}.
        </p>
        <p className="text-zinc-400 text-sm">Что сделать с аккаунтами?</p>
        <div className="flex flex-col gap-2 pt-1">
          <button
            onClick={() => onConfirm(false)}
            className="w-full bg-zinc-800 hover:bg-zinc-700 text-white py-2.5 rounded-xl text-sm font-medium transition-colors"
          >
            Оставить без профиля
          </button>
          <button
            onClick={() => onConfirm(true)}
            className="w-full bg-red-900/60 hover:bg-red-900 border border-red-800 text-red-300 py-2.5 rounded-xl text-sm font-medium transition-colors"
          >
            Удалить все аккаунты профиля
          </button>
          <button
            onClick={onCancel}
            className="w-full text-zinc-500 hover:text-zinc-300 py-2 text-sm transition-colors"
          >
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ProfilesPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingProfile, setEditingProfile] = useState<Profile | null>(null);
  const [deletingProfile, setDeletingProfile] = useState<Profile | null>(null);

  const { data: profiles = [], isLoading } = useQuery({
    queryKey: ["profiles"],
    queryFn: () => getProfiles(),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["profiles"] });

  const createMutation = useMutation({
    mutationFn: createProfile,
    onSuccess: () => { invalidate(); setShowForm(false); },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<ProfileInput> }) => updateProfile(id, data),
    onSuccess: () => { invalidate(); setEditingProfile(null); },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, deleteAccounts }: { id: number; deleteAccounts: boolean }) =>
      deleteProfile(id, deleteAccounts),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["accounts"] });
      setDeletingProfile(null);
    },
  });

  const filtered = profiles.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-black text-white">
      <header className="sticky top-0 z-10 bg-black/80 backdrop-blur border-b border-zinc-800 px-4 py-3">
        <div className="max-w-2xl mx-auto flex items-center gap-4">
          <Link to="/" className="text-zinc-400 hover:text-white transition-colors flex items-center gap-2 text-sm">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            Аккаунты
          </Link>
          <span className="text-zinc-600">/</span>
          <span className="text-zinc-300 font-medium">Профили</span>
          <button
            onClick={() => { setShowForm(true); setEditingProfile(null); }}
            className="ml-auto bg-white text-black text-sm font-semibold px-4 py-1.5 rounded-xl hover:bg-zinc-100 transition-colors"
          >
            + Создать
          </button>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-8 space-y-4">
        {/* Search */}
        <div className="relative">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
          </svg>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск профилей..."
            className="w-full bg-zinc-900 border border-zinc-800 rounded-xl pl-9 pr-4 py-2.5 text-sm text-white placeholder-zinc-500 focus:outline-none focus:border-zinc-600"
          />
        </div>

        {/* Create form */}
        {showForm && !editingProfile && (
          <ProfileForm
            initial={emptyForm()}
            onSave={data => createMutation.mutate(data)}
            onCancel={() => setShowForm(false)}
            loading={createMutation.isPending}
          />
        )}

        {isLoading && (
          <div className="flex justify-center py-12">
            <div className="w-6 h-6 border-2 border-zinc-600 border-t-transparent rounded-full animate-spin" />
          </div>
        )}

        {!isLoading && filtered.length === 0 && (
          <div className="text-center py-12 text-zinc-600 text-sm">
            {search ? "Профили не найдены" : "Профилей пока нет. Создайте первый."}
          </div>
        )}

        {filtered.map(profile => (
          editingProfile?.id === profile.id ? (
            <ProfileForm
              key={profile.id}
              initial={{ name: profile.name, description: profile.description, color: profile.color, avatar_url: profile.avatar_url }}
              onSave={data => updateMutation.mutate({ id: profile.id, data })}
              onCancel={() => setEditingProfile(null)}
              loading={updateMutation.isPending}
            />
          ) : (
            <ProfileCard
              key={profile.id}
              profile={profile}
              onEdit={p => { setEditingProfile(p); setShowForm(false); }}
              onDelete={setDeletingProfile}
            />
          )
        ))}
      </main>

      {/* Delete dialog */}
      {deletingProfile && (
        <DeleteDialog
          profile={deletingProfile}
          onConfirm={deleteAccounts => deleteMutation.mutate({ id: deletingProfile.id, deleteAccounts })}
          onCancel={() => setDeletingProfile(null)}
        />
      )}
    </div>
  );
}
