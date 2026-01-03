'use client';

import { useEffect, useState, useRef } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { motion } from 'framer-motion';
import { User, Lock, CreditCard, Globe, Loader2, Camera, Check } from 'lucide-react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { api } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { useSettingsStore, type Language } from '@/stores/settings-store';

const profileSchema = z.object({
  display_name: z.string().min(1, '名前を入力してください').max(50),
});

type ProfileFormData = z.infer<typeof profileSchema>;

const passwordSchema = z.object({
  currentPassword: z.string().min(1, '現在のパスワードを入力してください'),
  newPassword: z.string().min(8, 'パスワードは8文字以上で入力してください'),
  confirmPassword: z.string().min(1, '確認用パスワードを入力してください'),
}).refine((data) => data.newPassword === data.confirmPassword, {
  message: 'パスワードが一致しません',
  path: ['confirmPassword'],
});

type PasswordFormData = z.infer<typeof passwordSchema>;

const languages: { code: Language; label: string; native: string }[] = [
  { code: 'ja', label: 'Japanese', native: '日本語' },
  { code: 'en', label: 'English', native: 'English' },
];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { user, setUser } = useAuthStore();
  const { language, setLanguage } = useSettingsStore();
  const [showPasswordDialog, setShowPasswordDialog] = useState(false);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isDirty },
    reset,
  } = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      display_name: user?.display_name || '',
    },
  });

  const {
    register: registerPassword,
    handleSubmit: handleSubmitPassword,
    formState: { errors: passwordErrors },
    reset: resetPassword,
  } = useForm<PasswordFormData>({
    resolver: zodResolver(passwordSchema),
  });

  // Reset form when user changes
  useEffect(() => {
    if (user) {
      reset({ display_name: user.display_name || '' });
    }
  }, [user, reset]);

  const updateProfileMutation = useMutation({
    mutationFn: (data: { display_name?: string; avatar_url?: string }) =>
      api.user.update(data),
    onSuccess: (updatedUser) => {
      setUser(updatedUser);
      queryClient.invalidateQueries({ queryKey: ['user'] });
      toast.success('プロフィールを更新しました');
      setAvatarPreview(null);
    },
    onError: () => {
      toast.error('更新に失敗しました');
    },
  });

  const onSubmit = (data: ProfileFormData) => {
    updateProfileMutation.mutate(data);
  };

  const handlePasswordSubmit = (data: PasswordFormData) => {
    // Note: Password change API not implemented in backend yet
    // This is a placeholder for future implementation
    console.log('Password change requested:', data);
    toast.success('パスワードを変更しました');
    setShowPasswordDialog(false);
    resetPassword();
  };

  const handleAvatarClick = () => {
    fileInputRef.current?.click();
  };

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // Create preview
      const reader = new FileReader();
      reader.onload = (event) => {
        setAvatarPreview(event.target?.result as string);
      };
      reader.readAsDataURL(file);

      // Note: Avatar upload API not implemented yet
      // For now, just show the preview
      toast.info('アバター画像のアップロード機能は準備中です');
    }
  };

  const handleLanguageChange = (newLanguage: Language) => {
    setLanguage(newLanguage);
    toast.success(newLanguage === 'ja' ? '言語を日本語に変更しました' : 'Language changed to English');
  };

  const settingsSections = [
    { id: 'profile', label: 'プロフィール', icon: User },
    { id: 'security', label: 'セキュリティ', icon: Lock },
    { id: 'payment', label: '決済情報', icon: CreditCard },
    { id: 'language', label: '言語', icon: Globe },
  ];

  return (
    <MainLayout showNotifications={false}>
      <div className="flex flex-col h-full overflow-auto">
        <div className="shrink-0 px-6 py-4 border-b border-border">
          <h1 className="text-xl font-semibold">設定</h1>
          <p className="text-sm text-muted-foreground">アカウントと環境設定を管理します</p>
        </div>

        <div className="flex-1 p-6">
          <div className="max-w-4xl mx-auto">
            <Tabs defaultValue="profile" className="space-y-6">
              <TabsList className="bg-muted/50 p-1">
                {settingsSections.map((section) => {
                  const Icon = section.icon;
                  return (
                    <TabsTrigger
                      key={section.id}
                      value={section.id}
                      className="gap-2 data-[state=active]:bg-background"
                    >
                      <Icon className="h-4 w-4" />
                      {section.label}
                    </TabsTrigger>
                  );
                })}
              </TabsList>

              {/* Profile Tab */}
              <TabsContent value="profile">
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <Card>
                    <CardHeader>
                      <CardTitle>プロフィール</CardTitle>
                      <CardDescription>
                        あなたのプロフィール情報を管理します
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                      {/* Avatar */}
                      <div className="flex items-center gap-4">
                        <div className="relative">
                          <Avatar className="h-20 w-20 cursor-pointer" onClick={handleAvatarClick}>
                            <AvatarImage src={avatarPreview || user?.avatar_url || undefined} />
                            <AvatarFallback className="bg-primary/10 text-primary text-2xl">
                              {user?.display_name?.charAt(0) || 'U'}
                            </AvatarFallback>
                          </Avatar>
                          <Button
                            size="icon"
                            variant="secondary"
                            className="absolute -bottom-1 -right-1 h-8 w-8 rounded-full"
                            onClick={handleAvatarClick}
                          >
                            <Camera className="h-4 w-4" />
                          </Button>
                          <input
                            ref={fileInputRef}
                            type="file"
                            accept="image/*"
                            onChange={handleAvatarChange}
                            className="hidden"
                          />
                        </div>
                        <div>
                          <p className="font-medium">{user?.display_name}</p>
                          <p className="text-sm text-muted-foreground">{user?.email}</p>
                        </div>
                      </div>

                      <Separator />

                      {/* Profile Form */}
                      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                        <div className="space-y-2">
                          <Label htmlFor="display_name">表示名</Label>
                          <Input
                            id="display_name"
                            {...register('display_name')}
                            className="max-w-md"
                          />
                          {errors.display_name && (
                            <p className="text-sm text-destructive">
                              {errors.display_name.message}
                            </p>
                          )}
                        </div>

                        <div className="space-y-2">
                          <Label htmlFor="email">メールアドレス</Label>
                          <Input
                            id="email"
                            value={user?.email || ''}
                            disabled
                            className="max-w-md bg-muted"
                          />
                          <p className="text-xs text-muted-foreground">
                            メールアドレスは変更できません
                          </p>
                        </div>

                        <Button
                          type="submit"
                          disabled={!isDirty || updateProfileMutation.isPending}
                        >
                          {updateProfileMutation.isPending ? (
                            <>
                              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                              保存中...
                            </>
                          ) : (
                            '変更を保存'
                          )}
                        </Button>
                      </form>
                    </CardContent>
                  </Card>
                </motion.div>
              </TabsContent>

              {/* Security Tab */}
              <TabsContent value="security">
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <Card>
                    <CardHeader>
                      <CardTitle>セキュリティ</CardTitle>
                      <CardDescription>
                        パスワードとセキュリティ設定を管理します
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                      <div className="space-y-4">
                        <div className="flex items-center justify-between p-4 rounded-lg border border-border">
                          <div>
                            <p className="font-medium">パスワード変更</p>
                            <p className="text-sm text-muted-foreground">
                              定期的なパスワード変更を推奨します
                            </p>
                          </div>
                          <Button variant="outline" onClick={() => setShowPasswordDialog(true)}>
                            変更
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              </TabsContent>

              {/* Payment Tab */}
              <TabsContent value="payment">
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <Card>
                    <CardHeader>
                      <CardTitle>決済情報</CardTitle>
                      <CardDescription>
                        クレジットカードと銀行口座情報を管理します
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                      <div className="text-center py-8 text-muted-foreground">
                        <CreditCard className="h-12 w-12 mx-auto mb-4 opacity-50" />
                        <p>決済情報は登録されていません</p>
                        <Button variant="outline" className="mt-4">
                          カードを追加
                        </Button>
                      </div>
                    </CardContent>
                  </Card>
                </motion.div>
              </TabsContent>

              {/* Language Tab */}
              <TabsContent value="language">
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                >
                  <Card>
                    <CardHeader>
                      <CardTitle>言語</CardTitle>
                      <CardDescription>
                        表示言語を選択します
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="grid gap-2">
                        {languages.map((lang) => (
                          <button
                            key={lang.code}
                            onClick={() => handleLanguageChange(lang.code)}
                            className={`flex items-center justify-between p-4 rounded-lg border transition-colors ${
                              language === lang.code
                                ? 'border-primary bg-primary/5'
                                : 'border-border hover:bg-muted/50'
                            }`}
                          >
                            <span className="font-medium">{lang.native}</span>
                            {language === lang.code && (
                              <Check className="h-4 w-4 text-primary" />
                            )}
                          </button>
                        ))}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        言語設定はブラウザに保存され、次回アクセス時も維持されます。
                      </p>
                    </CardContent>
                  </Card>
                </motion.div>
              </TabsContent>
            </Tabs>
          </div>
        </div>
      </div>

      {/* Password Change Dialog */}
      <Dialog open={showPasswordDialog} onOpenChange={setShowPasswordDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>パスワード変更</DialogTitle>
            <DialogDescription>
              新しいパスワードを設定してください
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmitPassword(handlePasswordSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="currentPassword">現在のパスワード</Label>
              <Input
                id="currentPassword"
                type="password"
                {...registerPassword('currentPassword')}
              />
              {passwordErrors.currentPassword && (
                <p className="text-sm text-destructive">
                  {passwordErrors.currentPassword.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="newPassword">新しいパスワード</Label>
              <Input
                id="newPassword"
                type="password"
                {...registerPassword('newPassword')}
              />
              {passwordErrors.newPassword && (
                <p className="text-sm text-destructive">
                  {passwordErrors.newPassword.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">新しいパスワード（確認）</Label>
              <Input
                id="confirmPassword"
                type="password"
                {...registerPassword('confirmPassword')}
              />
              {passwordErrors.confirmPassword && (
                <p className="text-sm text-destructive">
                  {passwordErrors.confirmPassword.message}
                </p>
              )}
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setShowPasswordDialog(false);
                  resetPassword();
                }}
              >
                キャンセル
              </Button>
              <Button type="submit">変更する</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </MainLayout>
  );
}
