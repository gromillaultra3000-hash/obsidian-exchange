<?php

namespace App\Filament\Resources;

use App\Filament\Resources\PayoutQueueResource\Pages;
use App\Models\PayoutQueue;
use Filament\Tables;
use Filament\Tables\Table;

class PayoutQueueResource extends ReadOnlyResource
{
    protected static ?string $model = PayoutQueue::class;

    protected static ?string $navigationIcon = 'heroicon-o-banknotes';

    protected static ?string $navigationLabel = 'Выплаты';

    protected static ?string $modelLabel = 'выплата';

    protected static ?string $pluralModelLabel = 'выплаты';

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('order_id')
                    ->label('Заявка')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('currency'),
                Tables\Columns\TextColumn::make('amount')
                    ->label('Сумма')
                    ->numeric(8),
                Tables\Columns\TextColumn::make('crypto_address')
                    ->label('Адрес')
                    ->limit(20),
                Tables\Columns\TextColumn::make('status')
                    ->badge(),
                Tables\Columns\TextColumn::make('txid')
                    ->label('TXID')
                    ->limit(16)
                    ->toggleable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('status')
                    ->options([
                        'new' => 'new',
                        'sent' => 'sent',
                        'failed' => 'failed',
                    ]),
            ])
            ->actions([])
            ->bulkActions([]);
    }

    public static function canCreate(): bool
    {
        return false;
    }

    public static function getPages(): array
    {
        return [
            'index' => Pages\ListPayoutQueues::route('/'),
        ];
    }
}
