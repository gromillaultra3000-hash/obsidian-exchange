<?php

namespace App\Filament\Resources\SupportTicketResource\RelationManagers;

use Filament\Forms;
use Filament\Forms\Form;
use Filament\Resources\RelationManagers\RelationManager;
use Filament\Tables;
use Filament\Tables\Table;
use Illuminate\Support\Facades\Http;

class MessagesRelationManager extends RelationManager
{
    protected static string $relationship = 'messages';

    protected static ?string $title = 'Переписка';

    public function form(Form $form): Form
    {
        return $form
            ->schema([
                Forms\Components\Textarea::make('message')
                    ->label('Сообщение')
                    ->required()
                    ->maxLength(4000)
                    ->columnSpanFull(),
            ]);
    }

    public function table(Table $table): Table
    {
        return $table
            ->recordTitleAttribute('message')
            ->defaultSort('id')
            ->columns([
                Tables\Columns\TextColumn::make('sender')
                    ->label('От')
                    ->badge()
                    ->formatStateUsing(fn (string $state): string => $state === 'admin' ? 'Поддержка' : 'Клиент')
                    ->color(fn (string $state): string => $state === 'admin' ? 'success' : 'gray'),
                Tables\Columns\TextColumn::make('message')
                    ->label('Сообщение')
                    ->wrap(),
                Tables\Columns\TextColumn::make('created_at')
                    ->label('Дата')
                    ->dateTime('d.m.Y H:i'),
            ])
            ->headerActions([
                Tables\Actions\CreateAction::make()
                    ->label('Ответить')
                    ->mutateFormDataUsing(function (array $data): array {
                        return [
                            'message' => $data['message'],
                            'sender' => 'admin',
                            'created_at' => now(),
                        ];
                    })
                    ->after(function ($livewire) {
                        $ownerRecord = $livewire->getOwnerRecord();
                        $ownerRecord->status = 'answered';
                        $ownerRecord->updated_at = now();
                        $ownerRecord->save();

                        Http::withHeaders([
                            'X-Internal-Secret' => config('services.internal_admin_secret'),
                        ])->post(config('services.relay_internal_url') . '/internal/admin/notify_support', [
                            'web_user_id' => $ownerRecord->web_user_id,
                            'text' => "💬 Поддержка ответила на ваше обращение #{$ownerRecord->id} «{$ownerRecord->subject}». Посмотрите в личном кабинете на сайте.",
                        ]);
                    }),
            ])
            ->actions([])
            ->bulkActions([]);
    }
}
