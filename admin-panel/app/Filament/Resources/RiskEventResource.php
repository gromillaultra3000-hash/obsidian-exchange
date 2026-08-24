<?php

namespace App\Filament\Resources;

use App\Filament\Resources\RiskEventResource\Pages;
use App\Models\RiskEvent;
use Filament\Tables;
use Filament\Tables\Table;

class RiskEventResource extends ReadOnlyResource
{
    protected static ?string $model = RiskEvent::class;

    protected static ?string $navigationIcon = 'heroicon-o-shield-exclamation';

    protected static ?string $navigationLabel = 'Риск-события';

    protected static ?string $modelLabel = 'риск-событие';

    protected static ?string $pluralModelLabel = 'риск-события';

    public static function table(Table $table): Table
    {
        return $table
            ->defaultSort('id', 'desc')
            ->columns([
                Tables\Columns\TextColumn::make('telegram_id')
                    ->label('Telegram ID')
                    ->numeric()
                    ->sortable(),
                Tables\Columns\TextColumn::make('event_type')
                    ->label('Тип'),
                Tables\Columns\TextColumn::make('client_ip')
                    ->label('IP'),
                Tables\Columns\TextColumn::make('user_agent')
                    ->label('User-Agent')
                    ->limit(40)
                    ->toggleable(),
                Tables\Columns\TextColumn::make('created_at')
                    ->dateTime('d.m.Y H:i')
                    ->sortable(),
            ])
            ->filters([
                Tables\Filters\SelectFilter::make('event_type')
                    ->options(fn () => RiskEvent::query()
                        ->distinct()
                        ->pluck('event_type', 'event_type')
                        ->filter()
                        ->all()),
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
            'index' => Pages\ListRiskEvents::route('/'),
        ];
    }
}
